"""Crop Lifecycle Engine — dynamic planting-to-harvest calendar.

Uses real NASA POWER daily temperature to accumulate GDD since planting
and estimate the current growth stage, progress and harvest date.
Falls back to calendar-day fraction when GDD data is unavailable —
confidence is reported honestly in both cases.
"""
from datetime import date, timedelta

from core.services.nasa import fetch_power
from ..models import CropCycle

# Generic growth stages as fractions of total GDD (FAO-style phenology).
# Applied to any crop; crop-specific overrides can be added later.
STAGE_TEMPLATE = [
    (0.00, 0.10, 'جوانه‌زنی', 'آبیاری سبک و یکنواخت؛ مراقبت از بذر', 'سرما و خشکی سطحی'),
    (0.10, 0.35, 'رشد رویشی', 'آبیاری منظم؛ اولین کود نیتروژن', 'علف‌های هرز و آفات اولیه'),
    (0.35, 0.55, 'رشد زایشی', 'آبیاری عمیق‌تر؛ کوددهی مرحله‌ای', 'تنش گرمایی و کم‌آبی'),
    (0.55, 0.75, 'گل‌دهی / تشکیل میوه', 'آبیاری حساس؛ پایش بیماری', 'سرمازدگی و بارندگی شدید'),
    (0.75, 0.95, 'رسیدگی', 'کاهش آبیاری؛ آماده‌سازی برداشت', 'آفات و ریزش محصول'),
    (0.95, 1.01, 'برداشت', 'برداشت در زمان مناسب؛ کاهش تلفات', 'تأخیر برداشت و بارندگی'),
]


def _gdd_series(lat, lon, start, end, base_temp):
    """Fetch daily T2M and return (dates, gdd_list, tmean_list)."""
    power = fetch_power(lat, lon, start.strftime('%Y%m%d'), end.strftime('%Y%m%d'),
                        ['T2M', 'T2M_MAX', 'T2M_MIN'], community='AG', temporal='daily')
    maps = {}
    for p in power.get('parameters', []):
        maps[p['code']] = {pt['date']: pt['value'] for pt in p['points'] if pt['value'] is not None}
    dates = power.get('dates', [])
    gdds, tmeans = [], []
    for d in dates:
        tmax = maps.get('T2M_MAX', {}).get(d)
        tmin = maps.get('T2M_MIN', {}).get(d)
        tavg = maps.get('T2M', {}).get(d)
        if tavg is None and tmax is not None and tmin is not None:
            tavg = (tmax + tmin) / 2
        if tavg is None:
            continue
        gdd = max(0.0, tavg - base_temp)
        gdds.append(gdd)
        tmeans.append(tavg)
    return dates, gdds, tmeans


def get_lifecycle(cycle):
    """Return lifecycle status for a CropCycle."""
    crop = cycle.crop
    field = cycle.field
    today = date.today()
    planting = cycle.planting_date

    base = {
        'cycle_id': cycle.id, 'crop': crop.key, 'crop_name_fa': crop.name_fa,
        'field': field.name if field else None, 'planting_date': planting.isoformat(),
        'today': today.isoformat(),
    }

    if planting > today:
        base.update({'status': 'not_planted_yet', 'message_fa': 'تاریخ کاشت در آینده است'})
        return base

    days_since = (today - planting).days
    gdd_total = crop.gdd_total
    growth_days = crop.growth_days

    # --- try GDD-based progress ---
    gdd_accum = None
    method = 'calendar'
    confidence = 0.5
    if field and field.lat is not None and field.lon is not None and gdd_total:
        try:
            end = min(today, planting + timedelta(days=growth_days or 400))
            dates, gdds, _ = _gdd_series(field.lat, field.lon, planting, end, crop.base_temp_c)
            if gdds:
                gdd_accum = sum(gdds)
                method = 'gdd'
                confidence = 0.85
        except Exception:
            pass

    if gdd_accum is not None and gdd_total:
        progress = min(1.0, gdd_accum / gdd_total)
        # estimate harvest: remaining GDD / avg daily GDD
        avg_daily = gdd_accum / max(1, len(gdds)) if gdds else None
        remaining_days = None
        if avg_daily and avg_daily > 0 and progress < 1:
            remaining_days = int((gdd_total - gdd_accum) / avg_daily)
        est_harvest = (today + timedelta(days=remaining_days)).isoformat() if remaining_days else None
    elif growth_days:
        progress = min(1.0, days_since / growth_days)
        est_harvest = (planting + timedelta(days=growth_days)).isoformat()
        remaining_days = max(0, growth_days - days_since)
    else:
        progress = None
        est_harvest = None
        remaining_days = None

    # --- current stage ---
    current_stage = None
    if progress is not None:
        for lo, hi, name, tasks, risks in STAGE_TEMPLATE:
            if lo <= progress < hi:
                current_stage = {'name_fa': name, 'progress': round(progress, 3),
                                 'tasks_fa': tasks, 'risks_fa': risks}
                break
        if progress >= 1.0:
            current_stage = {'name_fa': 'برداشت (تکمیل دوره)', 'progress': 1.0,
                             'tasks_fa': 'برداشت و مدیریت پس از برداشت', 'risks_fa': 'تأخیر برداشت'}

    base.update({
        'days_since_planting': days_since,
        'gdd_accumulated': round(gdd_accum, 1) if gdd_accum is not None else None,
        'gdd_required': gdd_total,
        'progress': round(progress, 3) if progress is not None else None,
        'method': method, 'confidence': confidence,
        'estimated_harvest': est_harvest,
        'days_to_harvest': remaining_days,
        'current_stage': current_stage,
        'stages': [{'name_fa': s[2], 'from': s[0], 'to': s[1]} for s in STAGE_TEMPLATE],
    })
    return base
