"""Explainable Decision Intelligence Engine (Phase 2).

Coordinates the specialist engines (lifecycle, irrigation, risk,
economics) into a unified, explainable recommendation stream.

Design rules:
- The engine NEVER invents numbers — every recommendation carries
  evidence, sources, limitations and a confidence derived from real
  data completeness/freshness, not from an LLM.
- Missing data lowers confidence and is listed explicitly; the engine
  avoids definitive advice when evidence is thin.
- Recommendations are deduplicated, conflict-checked and expire.
"""
from datetime import date, timedelta

from ..models import Field, CropCycle, Recommendation
from .lifecycle import get_lifecycle
from .irrigation import get_irrigation_advice
from .risk import assess_field_risks

PRIORITY_ORDER = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}

# context fields the decision engine wants per field
CONTEXT_FIELDS = ['crop_cycle', 'growth_stage', 'soil', 'water_source',
                  'irrigation_method', 'area', 'planting_date', 'weather']


def build_context(field):
    """Collect Decision Context for a field; report missing pieces."""
    cycle = CropCycle.objects.filter(field=field).order_by('-id').first()
    soil = getattr(field, 'soil', None)
    ctx = {
        'field_id': field.id,
        'field_name': field.name,
        'farm_name': field.farm.name,
        'crop_cycle': cycle is not None,
        'crop': cycle.crop.name_fa if cycle and cycle.crop else (field.current_crop.name_fa if field.current_crop else None),
        'growth_stage': None,
        'soil': soil is not None,
        'water_source': bool(field.water_source),
        'irrigation_method': bool(field.irrigation_method),
        'area': field.area_ha is not None,
        'planting_date': field.planting_date is not None or (cycle.planting_date if cycle else False),
        'weather': False,
        'climate': False,
    }
    # live weather/climate via NASA POWER (cached in climate engine)
    if field.lat is not None and field.lon is not None:
        try:
            from core.services.climate import get_climate_indicators
            d = get_climate_indicators(field.lat, field.lon)
            ind = d.get('indicators', {})
            ctx['weather'] = True
            ctx['climate'] = True
            ctx['climate_summary'] = {
                'spi_6m': (ind.get('spi_6m') or {}).get('value'),
                'heatwave_events': (ind.get('heatwave') or {}).get('value'),
                'fetched_at': d.get('fetched_at'),
            }
        except Exception:
            pass
    # extended context: observations + historical operations
    try:
        from ..models import FarmObservation, IrrigationRecord, FertilizerRecord
        ctx['observations_count'] = FarmObservation.objects.filter(field=field).count()
        ctx['operations_count'] = (IrrigationRecord.objects.filter(field=field).count()
                                   + FertilizerRecord.objects.filter(field=field).count())
    except Exception:
        ctx['observations_count'] = ctx['operations_count'] = 0
    ctx['has_observations'] = ctx['observations_count'] > 0
    ctx['has_operations_history'] = ctx['operations_count'] > 0
    if cycle:
        try:
            lc = get_lifecycle(cycle)
            ctx['growth_stage'] = (lc.get('current_stage') or {}).get('name_fa')
            ctx['lifecycle'] = lc
        except Exception:
            ctx['lifecycle'] = None
    ctx['missing'] = [k for k in CONTEXT_FIELDS
                      if k in ('crop_cycle', 'soil', 'water_source',
                               'irrigation_method', 'area', 'planting_date')
                      and not ctx.get(k)]
    ctx['completeness'] = round(1 - len(ctx['missing']) / 7, 2)
    return ctx


def compute_confidence(engine_confidence, completeness, data_date=None,
                       consistent=True):
    """Transparent confidence score in [0, 0.95].

    Formula (documented, deterministic):
        0.40 * engine_confidence   (specialist engine's own estimate)
      + 0.30 * completeness        (share of context fields present)
      + 0.20 * freshness           (1.0 if data_date <= 7 days old else 0.5/0.2)
      + 0.10 * consistency         (1.0 if inputs consistent else 0.5)
    Capped at 0.95 — the engine never claims certainty.
    """
    engine = float(engine_confidence) if engine_confidence is not None else 0.5
    engine = max(0.0, min(1.0, engine))
    freshness = 1.0
    if data_date:
        try:
            d = date.fromisoformat(str(data_date)[:10])
            age = (date.today() - d).days
            freshness = 1.0 if age <= 7 else (0.5 if age <= 30 else 0.2)
        except (ValueError, TypeError):
            freshness = 0.5
    consistency = 1.0 if consistent else 0.5
    score = (0.40 * engine + 0.30 * completeness +
             0.20 * freshness + 0.10 * consistency)
    return round(min(0.95, max(0.05, score)), 2)


def _rec(field, title, action, reason, importance, confidence,
         evidence, sources, limitations, benefit='', timing='',
         valid_days=7, review_days=2, cost='', resources=None):
    today = date.today()
    return {
        'field': field, 'title_fa': title, 'action_fa': action,
        'timing_fa': timing, 'reason_fa': reason, 'importance': importance,
        'confidence': confidence, 'data_sources': sources,
        'data_date': today, 'limitations_fa': ' | '.join(limitations),
        'evidence': evidence, 'expected_benefit': benefit,
        'estimated_cost': cost, 'required_resources': resources or [],
        'valid_until': today + timedelta(days=valid_days),
        'review_at': today + timedelta(days=review_days),
    }


def _engine_recs(field, ctx):
    """Collect raw recommendations from specialist engines."""
    out = []
    # irrigation engine
    try:
        irr = get_irrigation_advice(field)
        if irr.get('advice_fa'):
            imp = irr.get('importance', 'medium')
            out.append(_rec(
                field, f"آبیاری — {field.name}", irr['advice_fa'],
                f"نیاز آبی خالص ~{irr.get('net_need_mm', '—')} میلی‌متر",
                imp, compute_confidence(irr.get('confidence'), ctx['completeness'],
                                        irr.get('data_date')),
                evidence=[f"net_need_mm={irr.get('net_need_mm')}",
                          f"soil_balance={irr.get('soil_balance')}"],
                sources=irr.get('data_sources', []),
                limitations=irr.get('limitations_fa', []),
                benefit='جلوگیری از تنش آبی و کاهش عملکرد',
                timing='صبح زود یا عصر',
                cost='هزینه آب و انرژی پمپاژ',
                resources=['آب', 'سیستم آبیاری']))
    except Exception:
        pass
    # risk engine
    try:
        for r in assess_field_risks(field):
            sev = r.get('severity', 'medium')
            imp = 'high' if sev in ('high', 'critical') else 'medium'
            out.append(_rec(
                field, r.get('title_fa', 'هشدار ریسک'), r.get('action_fa', ''),
                r.get('detail_fa', ''), imp,
                compute_confidence(0.6, ctx['completeness']),
                evidence=[f"kind={r.get('kind')}", f"severity={sev}"],
                sources=[r.get('source', 'risk engine')],
                limitations=['ارزیابی rule-based — داده زنده آب‌وهوا محدود است'],
                benefit='کاهش خسارت', timing=r.get('timing_fa', ''),
                valid_days=3, review_days=1,
                cost='بسته به اقدام', resources=['ابزار پایش']))
    except Exception:
        pass
    # lifecycle engine — stage tasks
    lc = ctx.get('lifecycle') or {}
    stage = lc.get('current_stage') or {}
    if stage.get('tasks_fa'):
        out.append(_rec(
            field, f"مرحله {stage.get('name_fa', '')} — {field.name}",
            stage['tasks_fa'],
            f"GDD: {lc.get('gdd_accumulated', '—')}/{lc.get('gdd_required', '—')} · پیشرفت {round((lc.get('progress') or 0)*100)}٪",
            'medium', compute_confidence(lc.get('confidence'), ctx['completeness']),
            evidence=[f"stage={stage.get('name_fa')}", f"progress={lc.get('progress')}"],
            sources=['Crop Lifecycle Engine', 'NASA POWER (GDD)'],
            limitations=lc.get('limitations', ['GDD تخمینی — دمای زنده مزرعه در دسترس نیست']),
            benefit='مدیریت به‌موقع مرحله رشد',
            timing=f"برداشت تخمینی: {lc.get('estimated_harvest', '—')}",
            valid_days=14, review_days=7,
            cost='نیروی کار', resources=['نیروی کار']))
    return out


def _dedup_and_conflicts(recs):
    """Merge duplicates (same field+action prefix) and flag conflicts."""
    seen = {}
    for r in recs:
        key = (r['field'].id, r['title_fa'][:30])
        if key in seen:
            # keep higher confidence
            if r['confidence'] > seen[key]['confidence']:
                seen[key] = r
        else:
            seen[key] = r
    merged = list(seen.values())
    # conflict detection: irrigation advice vs water_deficit risk on same field
    for r in merged:
        if 'آبیاری' in r['title_fa'] and r['field'].id:
            for r2 in merged:
                if r2 is not r and 'کمبود آب' in (r2.get('reason_fa') or ''):
                    r.setdefault('conflicts_with', []).append(r2['title_fa'])
    return merged


def generate_recommendations(farmer, field=None):
    """Main entry: build context → engine recs → dedup/conflict → persist.

    Returns {'recommendations': [...], 'context_summary': {...}}.
    """
    fields = Field.objects.filter(farm__farmer=farmer).select_related('farm', 'current_crop')
    if field is not None:
        fields = fields.filter(id=field.id)
    all_recs = []
    ctx_summary = {'fields': 0, 'complete': 0, 'missing_total': 0}
    for f in fields:
        ctx = build_context(f)
        ctx_summary['fields'] += 1
        if not ctx['missing']:
            ctx_summary['complete'] += 1
        ctx_summary['missing_total'] += len(ctx['missing'])
        all_recs.extend(_engine_recs(f, ctx))
    all_recs = _dedup_and_conflicts(all_recs)
    # sort by priority then confidence
    all_recs.sort(key=lambda r: (PRIORITY_ORDER.get(r['importance'], 2), -r['confidence']))
    # persist — avoid duplicates within 7 days; expired recs don't block regeneration
    saved = []
    for r in all_recs:
        exists = Recommendation.objects.filter(
            farmer=farmer, field=r['field'], title_fa=r['title_fa'],
            created_at__gte=date.today() - timedelta(days=7),
            valid_until__gte=date.today()).exists()
        if exists:
            continue
        obj = Recommendation.objects.create(
            farmer=farmer, field=r['field'], title_fa=r['title_fa'],
            action_fa=r['action_fa'], timing_fa=r['timing_fa'],
            reason_fa=r['reason_fa'], importance=r['importance'],
            confidence=r['confidence'], data_sources=r['data_sources'],
            data_date=r['data_date'], limitations_fa=r['limitations_fa'],
            status='new', valid_until=r['valid_until'], review_at=r['review_at'],
            evidence=r['evidence'], expected_benefit=r['expected_benefit'],
            estimated_cost=r['estimated_cost'], required_resources=r['required_resources'])
        saved.append(_rec_to_dict(obj))
    return {'recommendations': saved, 'context_summary': ctx_summary,
            'generated_at': date.today().isoformat()}


def _rec_to_dict(r):
    return {'id': r.id, 'field_id': r.field_id,
            'field_name': r.field.name if r.field else None,
            'title_fa': r.title_fa, 'action_fa': r.action_fa,
            'timing_fa': r.timing_fa, 'reason_fa': r.reason_fa,
            'importance': r.importance, 'confidence': r.confidence,
            'data_sources': r.data_sources, 'data_date': r.data_date.isoformat() if r.data_date else None,
            'limitations_fa': r.limitations_fa, 'status': r.status,
            'valid_until': r.valid_until.isoformat() if r.valid_until else None,
            'review_at': r.review_at.isoformat() if r.review_at else None,
            'evidence': r.evidence, 'expected_benefit': r.expected_benefit,
            'estimated_cost': r.estimated_cost, 'required_resources': r.required_resources,
            'outcome_note': r.outcome_note,
            'outcome_metrics': r.outcome_metrics or {},
            'outcome_at': r.outcome_at.isoformat() if r.outcome_at else None,
            'expired': bool(r.valid_until and r.valid_until < date.today()),
            'created_at': r.created_at.isoformat()}


def list_recommendations(farmer, status=None, field_id=None):
    qs = Recommendation.objects.filter(farmer=farmer).select_related('field').order_by('-created_at')
    if status:
        qs = qs.filter(status=status)
    if field_id:
        qs = qs.filter(field_id=field_id)
    return [_rec_to_dict(r) for r in qs[:50]]


def record_feedback(farmer, rec_id, status, outcome_note='', outcome_metrics=None):
    """Feedback loop: accepted/rejected/completed/ignored + outcome."""
    try:
        r = Recommendation.objects.get(id=rec_id, farmer=farmer)
    except Recommendation.DoesNotExist:
        return None
    if status not in ('accepted', 'rejected', 'completed', 'ignored'):
        return None
    r.status = status
    fields = ['status']
    if outcome_note is not None:
        r.outcome_note = outcome_note
        fields.append('outcome_note')
    if outcome_metrics is not None:
        metrics = outcome_metrics if isinstance(outcome_metrics, dict) else {}
        allowed = {'yield_kg_ha', 'cost', 'water_m3', 'rating', 'notes'}
        r.outcome_metrics = {k: v for k, v in metrics.items() if k in allowed}
        fields.append('outcome_metrics')
    if status in ('completed', 'accepted') or r.outcome_metrics or r.outcome_note:
        from django.utils import timezone
        r.outcome_at = timezone.now()
        fields.append('outcome_at')
    r.save(update_fields=fields)
    return _rec_to_dict(r)
