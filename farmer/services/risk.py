"""Agricultural Risk Engine — per-field risk assessment from real data.

Sources: NASA POWER via Climate Engine (SPI, heatwave, frost, water
balance). Each risk carries severity, probability, timing, affected
crop/field, suggested action and data source. Observation vs estimate
is distinguished in `kind`.
"""
from datetime import date

from core.services.climate import get_climate_indicators
from ..models import CropCycle


def assess_field_risks(field):
    """Return list of risk dicts for a field (empty if no coords/cycle)."""
    risks = []
    if field.lat is None or field.lon is None:
        return risks

    cycle = (CropCycle.objects.filter(field=field, status='active')
             .select_related('crop').order_by('-planting_date').first())
    crop = cycle.crop if cycle else None
    crop_name = crop.name_fa if crop else 'محصول نامشخص'

    try:
        d = get_climate_indicators(field.lat, field.lon)
    except Exception:
        return risks
    ind = d.get('indicators', {})
    monthly = d.get('monthly') or []
    today_month = date.today().strftime('%Y-%m')
    this_month = next((m for m in monthly if m['month'] == today_month), monthly[-1] if monthly else None)

    # --- drought (SPI-6) ---
    spi6 = ind.get('spi_6m', {}).get('value')
    if spi6 is not None:
        if spi6 <= -2.0:
            risks.append({'kind': 'drought', 'severity': 'critical', 'probability': 'high',
                          'title_fa': f'خشکسالی شدید (SPI-6={spi6:.1f}) — {crop_name} در معرض تنش آبی جدی',
                          'timing_fa': '۳ ماه گذشته تا ۳ ماه آینده', 'action_fa': 'آبیاری تکمیلی فوری؛ کاهش سطح زیر کشت در صورت تداوم',
                          'source': 'NASA POWER → SPI-6 (observed)'})
        elif spi6 <= -1.5:
            risks.append({'kind': 'drought', 'severity': 'high', 'probability': 'high',
                          'title_fa': f'خشکسالی متوسط (SPI-6={spi6:.1f})',
                          'timing_fa': '۳ ماه گذشته تا ۳ ماه آینده', 'action_fa': 'برنامه آبیاری منظم؛ پایش رطوبت خاک',
                          'source': 'NASA POWER → SPI-6 (observed)'})
        elif spi6 <= -1.0:
            risks.append({'kind': 'drought', 'severity': 'medium', 'probability': 'medium',
                          'title_fa': f'خشکسالی خفیف (SPI-6={spi6:.1f})',
                          'timing_fa': '۳ ماه گذشته تا ۳ ماه آینده', 'action_fa': 'آبیاری در مراحل حساس محصول',
                          'source': 'NASA POWER → SPI-6 (observed)'})

    # --- heat stress ---
    hw = ind.get('heatwave', {}).get('value', {})
    events = hw.get('events_ge3days', 0)
    if events and crop and crop.t_max_c:
        if events >= 2:
            risks.append({'kind': 'heat_stress', 'severity': 'high', 'probability': 'high',
                          'title_fa': f'{events} رویداد امواج گرما — {crop_name} در معرض تنش گرمایی (حد {crop.t_max_c}°C)',
                          'timing_fa': 'دوره تحلیل ۱۲ ماهه', 'action_fa': 'آبیاری در ساعات خنک؛ سایه‌بان در صورت امکان',
                          'source': 'NASA POWER → heatwave (observed)'})
        else:
            risks.append({'kind': 'heat_stress', 'severity': 'medium', 'probability': 'medium',
                          'title_fa': f'{events} رویداد امواج گرما — پایش تنش گرمایی {crop_name}',
                          'timing_fa': 'دوره تحلیل ۱۲ ماهه', 'action_fa': 'پایش روزانه دما؛ آبیاری سبک',
                          'source': 'NASA POWER → heatwave (observed)'})

    # --- frost risk ---
    frost = ind.get('frost_days', {}).get('value')
    if frost and crop and crop.t_min_c and frost > 0:
        month = date.today().month
        if month in (11, 12, 1, 2, 3):  # cold season
            risks.append({'kind': 'frost', 'severity': 'medium' if frost < 10 else 'high',
                          'probability': 'medium',
                          'title_fa': f'{frost} روز یخبندان در دوره — {crop_name} در مراحل حساس در معرض سرمازدگی',
                          'timing_fa': 'فصل سرد', 'action_fa': 'پوشش محافظ در شب‌های یخبندان؛ آبیاری سبک قبل از سرما',
                          'source': 'NASA POWER → T2M_MIN (observed)'})

    # --- heavy rain / disease risk ---
    if this_month and this_month.get('precip_mm') is not None:
        p = this_month['precip_mm']
        if p > 120:
            risks.append({'kind': 'heavy_rain', 'severity': 'medium', 'probability': 'medium',
                          'title_fa': f'بارش سنگین ماهانه ({p:.0f}mm) — خطر بیماری‌های قارچی و آب‌گرفتگی',
                          'timing_fa': this_month['month'], 'action_fa': 'پایش بیماری؛ بهبود زهکشی؛ کاهش آبیاری',
                          'source': 'NASA POWER → PRECTOTCORR (observed)'})

    # --- water deficit ---
    wb = ind.get('water_balance', {}).get('value')
    if wb is not None and wb < -100:
        risks.append({'kind': 'water_deficit', 'severity': 'high' if wb < -300 else 'medium',
                      'probability': 'high',
                      'title_fa': f'تراز آب منفی ({wb:.0f}mm) — کمبود آب در دوره',
                      'timing_fa': 'دوره تحلیل', 'action_fa': 'افزایش آبیاری؛ بررسی منبع آب',
                      'source': 'NASA POWER → water_balance (estimated)'})

    _persist_alerts(field, risks)
    return risks


def _fingerprint(field, kind):
    import hashlib
    return hashlib.sha256(f'{field.id}:{kind}'.encode()).hexdigest()[:32]


def _persist_alerts(field, risks):
    """Upsert RiskAlert rows with fingerprint dedup + lifecycle.

    Rules:
    - same fingerprint → update content, keep status (unless resolved/expired)
    - new fingerprint → status='new' (or 'active' if severity high/critical)
    - risk disappears → mark existing non-terminal alerts 'resolved'
    """
    from ..models import RiskAlert
    from django.utils import timezone
    farmer = field.farm.farmer
    seen_fps = set()
    for r in risks:
        kind = r.get('kind', 'unknown')
        fp = _fingerprint(field, kind)
        seen_fps.add(fp)
        sev = r.get('severity', 'medium')
        defaults = {
            'severity': sev,
            'title_fa': r.get('title_fa', '')[:160],
            'detail_fa': r.get('detail_fa', ''),
            'source': (r.get('source') or '')[:60],
            'evidence': [{'kind': kind, 'severity': sev,
                          'probability': r.get('probability', ''),
                          'timing': r.get('timing_fa', '')}],
            'expires_at': None,
        }
        obj, created = RiskAlert.objects.get_or_create(
            fingerprint=fp, farmer=farmer,
            defaults={**defaults, 'field': field, 'kind': kind,
                      'status': 'active' if sev in ('high', 'critical') else 'new'})
        if not created:
            # refresh content; reactivate if was resolved/expired
            for k, v in defaults.items():
                setattr(obj, k, v)
            if obj.status in ('resolved', 'expired'):
                obj.status = 'active' if sev in ('high', 'critical') else 'new'
                obj.resolved_at = None
            elif obj.status == 'new' and sev in ('high', 'critical'):
                obj.status = 'active'
            obj.save()
    # resolve alerts whose risk disappeared
    stale = RiskAlert.objects.filter(
        field=field, farmer=farmer, dismissed=False,
        status__in=('new', 'active', 'acknowledged', 'snoozed'))
    for a in stale:
        if not a.fingerprint or a.fingerprint not in seen_fps:
            a.status = 'resolved'
            a.resolved_at = timezone.now()
            a.save(update_fields=['status', 'resolved_at', 'updated_at'])
