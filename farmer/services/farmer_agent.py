"""Farmer Agent — controlled intents over the tool registry (Phase 6).

The agent classifies the user's goal, selects an allow-listed tool, lets
the specialist engine do all numeric work, preserves per-farmer context,
and never executes mutating tools without an explicit confirmation step.
"""
import re

from core.services.agent_intents import resolve_intent
from core.services.tools import AgentContext, get_context, save_context, ToolError

from ..models import Field, CropCycle, FarmObservation
from .tools import get_registry


# Legacy engine intents kept for backward-compatible API responses.
_LEGACY_RULES = [
    ('recommend', ['چه محصول', 'محصول مناسب', 'چی بکارم', 'کدام محصول', 'suggest crop', 'what crop']),
    ('daily', ['امروز', 'چه کار کنم', 'کارهای امروز', 'daily', 'what to do today']),
    ('irrigation', ['آبیاری', 'آب', 'irrigation', 'water']),
    ('lifecycle', ['برداشت', 'مرحله رشد', 'وضعیت محصول', 'harvest', 'growth stage', 'کی برداشت']),
    ('risk', ['خطر', 'هشدار', 'ریسک', 'خشکسالی', 'سرما', 'گرما', 'risk', 'warning', 'drought']),
    ('economics', ['هزینه', 'سود', 'درآمد', 'اقتصاد', 'قیمت', 'cost', 'profit', 'economics']),
    ('diagnosis', ['بیماری', 'آفت', 'علائم', 'زردی', 'لکه', 'diagnos', 'disease', 'pest']),
]

_UNKNOWN_FA = ('متوجه سؤال نشدم. می‌توانید بپرسید: «چه محصولی بکارم؟»، «امروز چه کار کنم؟»، '
               '«آبیاری چقدر؟»، «برداشت کیه؟»، «هزینه‌ها چقدر؟»، «چه خطراتی هست؟».')
_SUGGESTIONS = ['چه محصولی بکارم؟', 'امروز چه کار کنم؟', 'آبیاری چقدر؟', 'برداشت کیه؟', 'هزینه‌ها چقدر؟']


def _detect_intent(q):
    q = (q or '').lower()
    for intent, kws in _LEGACY_RULES:
        if any(k in q for k in kws):
            return intent
    return None


def _pick_field(farmer, question):
    fields = list(Field.objects.filter(farm__farmer=farmer).select_related('farm', 'current_crop'))
    if not fields:
        return None, False
    if len(fields) == 1:
        return fields[0], False
    for f in fields:
        if f.name and f.name in question:
            return f, False
    return None, True


def _context(farmer):
    ctx = get_context(getattr(farmer, 'api_key', f'farmer:{farmer.id}'))
    ctx.farmer = farmer
    return ctx


def _persist(ctx):
    """Save context without pickling the farmer instance."""
    farmer = getattr(ctx, 'farmer', None)
    if hasattr(ctx, 'farmer'):
        del ctx.farmer
    ctx.history = (ctx.history or [])[-10:]
    save_context(ctx)
    ctx.farmer = farmer
    return ctx


def _sync_context(ctx, field=None, intent=None):
    if field is not None:
        ctx.active_field_id = field.id
        ctx.active_farm_id = field.farm_id
        cycle = CropCycle.objects.filter(field=field, status='active').select_related('crop').order_by('-planting_date').first()
        crop_key = cycle.crop.key if cycle and cycle.crop else (field.current_crop.key if field.current_crop else None)
        ctx.active_crop = crop_key
        if cycle is None:
            ctx.growth_stage = None
    if intent:
        ctx.current_task = intent
    try:
        if getattr(ctx, 'active_field_id', None):
            obs = (FarmObservation.objects.filter(field_id=ctx.active_field_id)
                   .order_by('-observed_at')[:3])
            ctx.recent_observations = [{'id': o.id, 'note': o.note[:160]} for o in obs]
        else:
            ctx.recent_observations = []
    except Exception:
        pass
    return ctx


def _run_tool(ctx, name, params):
    try:
        out = get_registry().run(name, params or {}, context=ctx)
        result = out.get('result') if isinstance(out, dict) else out
        if name in ('get_crop_status', 'get_lifecycle_status') and isinstance(result, dict):
            ctx.growth_stage = result.get('growth_stage')
            ctx.active_crop = result.get('crop') or ctx.active_crop
        return result
    except ToolError as e:
        return {'error': str(e), 'tool_error': True}
    except Exception as e:  # defensive: never leak stack traces to the client
        return {'error': f'tool {name} failed: {e}', 'tool_error': True}


def _field_choices(farmer, intent):
    fields = Field.objects.filter(farm__farmer=farmer).select_related('farm')
    return {'intent': intent, 'answer_fa': 'چند قطعه زمین دارید — نام قطعه را بگویید (مثلاً «قطعه ۱»).',
            'fields': [{'id': f.id, 'name': f.name} for f in fields]}


def _needs_field(intent):
    return intent in {'weather', 'irrigation', 'lifecycle', 'recommend', 'risk', 'diagnosis'}


def _select_field(farmer, q, field_id, ctx):
    if field_id:
        fl = Field.objects.filter(id=field_id, farm__farmer=farmer).select_related('farm', 'current_crop').first()
        if fl is None:
            return None, None, {'error': 'قطعه زمین یافت نشد یا متعلق به شما نیست.'}
        return fl, False, None
    field, needs_choice = _pick_field(farmer, q)
    if needs_choice:
        return None, True, None
    return field, False, None


def _finish(ctx, result, mode='simple'):
    result.setdefault('mode', mode)
    result.setdefault('sources', result.get('sources') or result.get('data_sources') or [])
    result.setdefault('limitations', result.get('limitations') or result.get('limitations_fa') or [])
    if mode == 'expert':
        result['expert'] = {'sources': result.get('sources'),
                            'limitations': result.get('limitations'),
                            'details': result.get('details')}
    _persist(ctx)
    return result


def _base_result(intent, resolved, ctx, mode):
    return {'intent': intent, 'resolved_intent': resolved.get('intent'),
            'confidence': resolved.get('confidence'), 'mode': mode,
            'context': {'active_farm_id': ctx.active_farm_id, 'active_field_id': ctx.active_field_id,
                        'active_crop': ctx.active_crop, 'growth_stage': ctx.growth_stage,
                        'current_task': ctx.current_task}}


def _answer_daily(ctx, farmer):
    d = _run_tool(ctx, 'get_daily_briefing', {})
    if d.get('error'):
        return {'answer_fa': d['error'], 'details': d}
    return {'answer_fa': d.get('summary_fa') or '—', 'details': d,
            'sources': d.get('data_sources'), 'limitations': d.get('limitations')}


def _answer_weather(ctx, field):
    d = _run_tool(ctx, 'get_weather', {'field_id': field.id, 'days': 7})
    if d.get('error'):
        return {'answer_fa': f"برای {field.name}: {d['error']}", 'details': d}
    ans = (f"هوای ۷ روز گذشته در {field.name}: میانگین دما {d.get('avg_temp_c', '—')}°C، "
           f"مجموع بارش {d.get('rain_total_mm', '—')} میلی‌متر، میانگین رطوبت {d.get('avg_humidity_pct', '—')}٪.")
    return {'answer_fa': ans, 'details': d, 'sources': d.get('data_sources'), 'limitations': d.get('limitations')}


def _answer_irrigation(ctx, field):
    d = _run_tool(ctx, 'get_irrigation_status', {'field_id': field.id})
    if d.get('error') and not d.get('advice_fa'):
        return {'answer_fa': d.get('error') or 'داده کافی برای توصیه آبیاری موجود نیست.', 'details': d}
    return {'answer_fa': d.get('advice_fa') or d.get('error') or '—', 'details': d,
            'sources': d.get('data_sources'), 'limitations': d.get('limitations_fa')}


def _answer_lifecycle(ctx, field):
    d = _run_tool(ctx, 'get_crop_status', {'field_id': field.id})
    if d.get('status') == 'no_active_cycle':
        return {'answer_fa': d.get('message_fa') or f'برای {field.name} چرخه کاشت فعالی نیست.', 'details': d}
    if d.get('error'):
        return {'answer_fa': d['error'], 'details': d}
    ans = f"{d.get('crop_name_fa') or 'محصول'} در {field.name}: مرحله {d.get('growth_stage') or 'نامشخص'}، پیشرفت {round((d.get('progress') or 0) * 100)}٪."
    if d.get('estimated_harvest'):
        ans += f" برداشت تخمینی: {d['estimated_harvest']}."
    return {'answer_fa': ans, 'details': d, 'sources': d.get('data_sources'), 'limitations': d.get('limitations')}


def _answer_recommend(ctx, field):
    d = _run_tool(ctx, 'get_crop_recommendation', {'field_id': field.id, 'top': 5})
    if d.get('error'):
        return {'answer_fa': d['error'], 'details': d}
    ranking = d.get('ranking') or []
    top = ranking[:3]
    ans = 'محصولات پیشنهادی برای ' + field.name + ': ' + '، '.join(
        f"{r.get('name_fa')} ({round(r.get('score') or 0)})" for r in top) + '.' if top else 'پیشنهاد محصول در دسترس نیست.'
    return {'answer_fa': ans, 'details': d, 'sources': d.get('data_sources'), 'limitations': d.get('limitations')}


def _answer_risk(ctx, field):
    d = _run_tool(ctx, 'get_active_risks', {'field_id': field.id})
    risks = (d.get('risks') or d.get('result', {}).get('risks') or []) if isinstance(d, dict) else []
    if not risks:
        return {'answer_fa': f'ریسک قابل‌توجهی برای {field.name} شناسایی نشد.', 'details': {'risks': []}}
    ans = f"{len(risks)} ریسک برای {field.name}: " + '؛ '.join(r.get('title_fa', '') for r in risks[:3])
    return {'answer_fa': ans, 'details': {'risks': risks},
            'sources': ['NASA POWER → SPI/heatwave/frost'], 'limitations': ['ریسک‌ها بر اساس داده تاریخی‌اند، نه پیش‌بینی.']}


def _answer_economics(ctx, farmer):
    farm = farmer.farms.first()
    if farm is None:
        return {'answer_fa': 'ابتدا مزرعه ثبت کنید.'}
    d = _run_tool(ctx, 'get_farm_economics', {'farm_id': farm.id})
    if d.get('error'):
        return {'answer_fa': d['error'], 'details': d}
    ans = f"هزینه کل مزرعه {farm.name}: {d.get('total_cost', 0):,.0f}"
    if d.get('cost_per_ha'):
        ans += f" (هزینه/هکتار: {d['cost_per_ha']:,.0f})"
    if 'profit' in d:
        ans += f". سود تخمینی: {d['profit']:,.0f} — حاشیه {d.get('margin_pct')}٪."
    else:
        ans += '. برای محاسبه سود، عملکرد و قیمت فروش را در بخش اقتصاد وارد کنید.'
    return {'answer_fa': ans, 'details': d, 'sources': d.get('data_sources'), 'limitations': d.get('limitations_fa')}


def _answer_diagnosis(ctx, field, q):
    symptoms = re.split(r'[،,؛;]| و ', q)
    symptoms = [s for s in symptoms if len(s) > 2]
    d = _run_tool(ctx, 'diagnose_field', {'field_id': field.id, 'symptoms': '، '.join(symptoms)})
    if d.get('error'):
        return {'answer_fa': d['error'], 'details': d}
    causes = '، '.join(c.get('cause', '') for c in (d.get('possible_causes') or [])[:3])
    return {'answer_fa': f"علل محتمل: {causes}. قبل از سم‌پاشی با کارشناس گیاه‌پزشکی مشورت کنید.",
            'details': d, 'sources': ['Symptom rule-base'], 'limitations': d.get('limitations_fa')}


def _operation_parts(q):
    ql = q.lower()
    if any(k in ql for k in ['مشاهده', 'یادداشت', 'note', 'observation']):
        return 'create_observation', 'note'
    if any(k in ql for k in ['کار', 'وظیفه', 'task', 'یادآوری', 'reminder']):
        return 'create_farm_task', 'title'
    return 'create_farm_task', 'title'


def _answer_operation(ctx, farmer, q, field_id, mode):
    tool_name, param_key = _operation_parts(q)
    field = None
    if tool_name == 'create_observation' or field_id:
        field, needs_choice, err = _select_field(farmer, q, field_id, ctx)
        if err:
            return {'answer_fa': err['error']}
        if needs_choice:
            return _field_choices(farmer, 'farm_operation')
        if field is None:
            return {'answer_fa': 'برای ثبت مشاهده ابتدا قطعه زمین را مشخص کنید.'}
    params = {'field_id': field.id if field else None}
    text = re.sub(r'(لطفا|please|ثبت کن|ثبت|save|record|log|add|create|new)', '', q, flags=re.I).strip(' ؟?') or q
    if param_key == 'note':
        params['note'] = text[:1000]
    else:
        params['title'] = text[:160]
    preview = {k: v for k, v in params.items() if v not in (None, '')}
    _sync_context(ctx, field=field, intent='farm_operation')
    return {'intent': 'farm_operation', 'resolved_intent': 'farm_operation',
            'confirmation_required': True, 'tool': tool_name, 'params': params,
            'preview': preview,
            'message_fa': 'این عملیات داده مزرعه را تغییر می‌دهد — فقط پس از تأیید شما اجرا می‌شود.',
            'answer_fa': 'برای ثبت این مورد تأیید کنید.', 'mode': mode}


def _answer_scientific(ctx, q, resolved):
    d = _run_tool(ctx, 'get_scientific_datasets', {'keyword': q[:120], 'limit': 3})
    items = d.get('items') or []
    if items:
        titles = '؛ '.join((i.get('title') or i.get('short_name') or '')[:80] for i in items[:3])
        ans = f"در کاتالوگ NASA CMR این موارد مرتبط پیدا شد: {titles}. این‌ها متادیتای کاتالوگ هستند، نه داده پردازش‌شده."
    else:
        ans = ('برای جستجوی دقیق ماهواره‌ای و کاتالوگ داده از Earth Intelligence (/observatory/) استفاده کنید. '
               'در صورت نبود داده مرتبط، نتیجه ساختگی ارائه نمی‌شود.')
    return {'answer_fa': ans, 'details': {'items': items, 'hits': d.get('hits')},
            'sources': d.get('data_sources') or ['NASA Earthdata CMR'],
            'limitations': d.get('limitations') or ['Catalog metadata only — not downloaded data values.']}


def answer(farmer, question, field_id=None, mode='simple'):
    """Main entry: question → intent → tool → simple/expert answer."""
    q = (question or '').strip()
    if not q:
        return {'answer_fa': 'سؤال خود را بنویسید.', 'intent': None}
    mode = 'expert' if (mode or '').lower() == 'expert' else 'simple'
    ctx = _context(farmer)
    resolved = resolve_intent(q)
    canonical = resolved.get('intent')
    legacy = _detect_intent(q)
    hist_intent = 'farm_operation' if canonical == 'farm_operation' else (legacy or canonical)
    ctx.history = (ctx.history or [])[-9:] + [{'q': q[:200], 'intent': hist_intent}]

    # Explicit mutating intent — never executes without confirmation.
    if canonical == 'farm_operation':
        return _finish(ctx, _answer_operation(ctx, farmer, q, field_id, mode), mode)

    # Scientific/satellite requests are routed to read-only catalog metadata.
    if canonical in ('scientific_research', 'satellite_search'):
        out = _base_result(canonical, resolved, ctx, mode)
        out.update(_answer_scientific(ctx, q, resolved))
        out['intent'] = canonical
        return _finish(ctx, out, mode)

    # Weather is field-scoped and uses the controlled weather tool.
    if canonical == 'weather_query':
        legacy = 'weather'
    elif legacy is None and canonical != 'general_question':
        legacy = None

    if legacy is None:
        out = _base_result(None, resolved, ctx, mode)
        out.update({'answer_fa': _UNKNOWN_FA, 'suggestions': _SUGGESTIONS,
                    'sources': [], 'limitations': ['سؤال خارج از دامنه ابزارهای موجود است.']})
        return _finish(ctx, out, mode)

    # Field-scoped intents
    if _needs_field(legacy) or legacy == 'weather':
        field, needs_choice, err = _select_field(farmer, q, field_id, ctx)
        if err:
            return _finish(ctx, {'answer_fa': err['error'], 'intent': legacy}, mode)
        if needs_choice:
            out = _field_choices(farmer, legacy)
            _sync_context(ctx, intent=legacy)
            return _finish(ctx, out, mode)
        if field is None:
            return _finish(ctx, {'answer_fa': 'ابتدا مزرعه و قطعه زمین ثبت کنید.', 'intent': legacy}, mode)
        _sync_context(ctx, field=field, intent=legacy)
        if legacy == 'weather':
            body = _answer_weather(ctx, field)
        elif legacy == 'irrigation':
            body = _answer_irrigation(ctx, field)
        elif legacy == 'lifecycle':
            body = _answer_lifecycle(ctx, field)
        elif legacy == 'recommend':
            body = _answer_recommend(ctx, field)
        elif legacy == 'risk':
            body = _answer_risk(ctx, field)
        elif legacy == 'diagnosis':
            body = _answer_diagnosis(ctx, field, q)
        else:
            body = {'answer_fa': 'این قصد پشتیبانی نمی‌شود.'}
        out = _base_result(legacy, resolved, ctx, mode)
        out.update(body)
        out['tools_used'] = [out.get('details', {}).get('tool') if isinstance(out.get('details'), dict) else None]
        return _finish(ctx, out, mode)

    # Farm-level intents
    _sync_context(ctx, intent=legacy)
    if legacy == 'daily':
        body = _answer_daily(ctx, farmer)
    elif legacy == 'economics':
        body = _answer_economics(ctx, farmer)
    else:
        body = {'answer_fa': 'این قصد پشتیبانی نمی‌شود.'}
    out = _base_result(legacy, resolved, ctx, mode)
    out.update(body)
    return _finish(ctx, out, mode)
