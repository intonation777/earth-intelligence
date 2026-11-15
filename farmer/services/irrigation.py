"""Irrigation Engine v2 — FAO-56 based (Phase 3).

ET0: FAO-56 Penman-Monteith from NASA POWER daily params (et0.py)
     fallback: Hargreaves → monthly PET (Climate Engine)
ETc = Kc × ET0  (Kc = crop.kc_max × stage factor — documented curve)
Soil water balance: TAW/RAW/depletion when SoilProfile complete
Scheduling: net→gross depth via irrigation efficiency, volume = depth×area

API-compatible with v1: same keys + new 'et0_engine', 'scheduling' blocks.
"""
from datetime import date

from core.services.climate import get_climate_indicators
from .lifecycle import get_lifecycle, STAGE_TEMPLATE
from .et0 import get_et0_daily
from ..models import CropCycle

# Kc stage curve — FAO-56 style multipliers on crop.kc_max
STAGE_KC_FACTOR = [0.4, 0.7, 0.9, 1.0, 0.9, 0.5]
EFFECTIVE_RAIN_FACTOR = 0.8
# irrigation efficiency by method (documented typical values)
IRR_EFFICIENCY = {'drip': 0.90, 'sprinkler': 0.75, 'surface': 0.60,
                  'flood': 0.50, 'manual': 0.50}
DEFAULT_EFFICIENCY = 0.70


def _current_stage_index(progress):
    if progress is None:
        return 2
    for i, (lo, hi, *_) in enumerate(STAGE_TEMPLATE):
        if lo <= progress < hi:
            return i
    return len(STAGE_TEMPLATE) - 1


def _kc_for_stage(crop, stage_idx):
    """Kc = crop.kc_max × stage factor; documented, not invented."""
    kc_max = crop.kc_max or 1.0
    return round(kc_max * STAGE_KC_FACTOR[stage_idx], 3)


def _efficiency(method):
    m = (method or '').lower()
    for k, v in IRR_EFFICIENCY.items():
        if k in m:
            return v, k
    return DEFAULT_EFFICIENCY, 'default'


def get_irrigation_advice(field):
    cycle = (CropCycle.objects.filter(field=field, status='active')
             .select_related('crop', 'field').order_by('-planting_date').first())
    if cycle is None:
        return {'error': 'چرخه کاشت فعالی برای این قطعه یافت نشد', 'advice_fa': None}

    crop = cycle.crop
    life = get_lifecycle(cycle) or {}
    progress = life.get('progress')
    stage_idx = _current_stage_index(progress)
    stage_name = (life.get('current_stage') or {}).get('name_fa', 'نامشخص')
    kc = _kc_for_stage(crop, stage_idx)

    limitations = []
    confidence = 0.6

    # --- ET0 engine (FAO-56 PM daily) ---
    et0_data = {'series': [], 'method': 'unavailable'}
    if field.lat is not None and field.lon is not None:
        try:
            et0_data = get_et0_daily(field, days=30)
        except Exception as e:
            et0_data = {'series': [], 'method': 'unavailable',
                        'limitations': [str(e)]}

    series = et0_data.get('series') or []
    etc_series = []
    total_etc = 0.0
    total_rain = 0.0
    for pt in series:
        et0 = pt.get('et0_mm')
        rain = pt.get('precip_mm')
        if et0 is not None:
            etc = round(et0 * kc, 2)
            total_etc += etc
            etc_series.append({'date': pt['date'], 'et0': et0, 'etc': etc})
        if rain is not None:
            total_rain += rain

    days_with_data = len(etc_series)
    avg_daily_etc = round(total_etc / days_with_data, 2) if days_with_data else None
    avg_daily_rain = round(total_rain / days_with_data, 2) if days_with_data else None
    eff_rain_total = round(total_rain * EFFECTIVE_RAIN_FACTOR, 1) if days_with_data else None
    net_need_total = round(total_etc - eff_rain_total, 1) if days_with_data and eff_rain_total is not None else None

    # fallback: monthly PET from Climate Engine
    monthly_pet = None
    if days_with_data == 0:
        try:
            climate = get_climate_indicators(field.lat, field.lon)
            monthly = climate.get('monthly') or []
            cm = date.today().strftime('%Y-%m')
            this_month = next((m for m in monthly if m['month'] == cm), monthly[-1] if monthly else None)
            if this_month:
                monthly_pet = this_month.get('pet_mm')
        except Exception:
            pass

    # --- soil water balance ---
    soil = getattr(field, 'soil', None)
    soil_balance = None
    if soil and soil.field_capacity and soil.wilting_point and soil.root_depth_cm and field.area_ha:
        taw = round((soil.field_capacity - soil.wilting_point) * soil.root_depth_cm * field.area_ha * 10, 1)
        raw = round(taw * 0.5, 1)
        depletion = None
        if net_need_total is not None and raw:
            # net_need mm → m³: mm/1000 × ha × 10000 = mm × ha × 10
            need_m3 = net_need_total * field.area_ha * 10
            depletion = round(min(need_m3 / raw, 1.0), 2)
        soil_balance = {'taw_m3': taw, 'raw_m3': raw,
                        'depletion_frac': depletion,
                        'note_fa': 'TAW/RAW بر اساس FC/PWP/عمق ریشه — RAW≈۵۰٪ TAW'}

    # --- irrigation scheduling ---
    eff, eff_name = _efficiency(field.irrigation_method)
    scheduling = None
    if net_need_total is not None and field.area_ha:
        daily_net_mm = net_need_total / max(days_with_data, 1)
        gross_mm = round(daily_net_mm / eff, 1)
        volume_m3 = round(gross_mm / 1000 * field.area_ha * 10000, 1)
        scheduling = {
            'daily_net_mm': round(daily_net_mm, 2),
            'daily_gross_mm': gross_mm,
            'daily_volume_m3': volume_m3,
            'efficiency': eff, 'efficiency_basis': eff_name,
            'timing_fa': 'آبیاری در ساعات خنک (صبح زود/عصر) برای کاهش تبخیر',
        }

    # --- uncertainty ---
    if days_with_data == 0:
        limitations.append('داده ET0 روزانه POWER در دسترس نیست — از PET ماهانه هارگریوز استفاده شد یا داده کافی نیست.')
        confidence = 0.3
    else:
        limitations.append(f'ET0 با FAO-56 PM از {days_with_data} روز داده POWER محاسبه شد (method={et0_data.get("method")}).')
        confidence = 0.75
    if soil_balance is None:
        limitations.append('اطلاعات خاک (FC/PWP/عمق ریشه) ناقص — تراز آب خاک و حجم دقیق آبیاری محاسبه نشد.')
        confidence = max(0.2, confidence - 0.15)
    if field.irrigation_method in ('', None):
        limitations.append('روش آبیاری مشخص نیست — بازده پیش‌فرض ۷۰٪ استفاده شد.')
        confidence = max(0.2, confidence - 0.1)
    limitations.append('Kc = kc_max محصول × ضریب مرحله رشد (منحنی FAO-56 تقریبی).')
    limitations.append('این توصیه جایگزین نظر کارشناس آبیاری نیست.')

    # --- advice text ---
    if net_need_total is not None:
        if net_need_total <= 0:
            action = 'نیاز آبی خالص دوره منفی است — آبیاری اضافه لازم نیست مگر تنش رطوبت خاک مشاهده شود.'
            importance = 'low'
        elif net_need_total < 30:
            action = f'نیاز آبی خالص ~{net_need_total} میلی‌متر در دوره — آبیاری سبک و یکنواخت کافی است.'
            importance = 'medium'
        else:
            vol_txt = f' (~{scheduling["daily_volume_m3"]} مترمکعب/روز)' if scheduling else ''
            action = f'نیاز آبی خالص ~{net_need_total} میلی‌متر در دوره{vol_txt} — آبیاری منظم در مراحل حساس توصیه می‌شود.'
            importance = 'high'
    elif monthly_pet is not None:
        etc_m = round(monthly_pet * kc, 1)
        action = f'PET ماه ~{monthly_pet}mm × Kc={kc} → ETc ~{etc_m}mm — برای مقدار دقیق، داده روزانه POWER لازم است.'
        importance = 'medium'
    else:
        action = 'اطلاعات کافی برای محاسبه نیاز آبی نیست — وضعیت رطوبت خاک را بررسی و در صورت نیاز آبیاری کنید.'
        importance = 'medium'

    return {
        'field_id': field.id, 'field_name': field.name,
        'crop': crop.key, 'crop_name_fa': crop.name_fa,
        'growth_stage': stage_name, 'progress': progress,
        'kc_used': kc, 'stage_kc_factor': STAGE_KC_FACTOR[stage_idx],
        'et0_engine': {'method': et0_data.get('method'), 'days': days_with_data,
                       'avg_daily_et0': round(sum(p['et0'] for p in etc_series) / days_with_data, 2) if days_with_data else None},
        'etc_daily_series': etc_series[-7:],
        'avg_daily_etc_mm': avg_daily_etc, 'avg_daily_rain_mm': avg_daily_rain,
        'etc_total_mm': round(total_etc, 1) if days_with_data else None,
        'effective_rain_mm': eff_rain_total,
        'net_need_mm': net_need_total,
        'monthly_pet_fallback': monthly_pet,
        'soil_balance': soil_balance,
        'scheduling': scheduling,
        'advice_fa': action, 'importance': importance,
        'confidence': round(confidence, 2), 'limitations_fa': limitations,
        'data_sources': ['NASA POWER (ET0 FAO-56 PM daily)', 'CropProfile Kc',
                         'SoilProfile (incomplete → noted)', 'Field input',
                         'FAO-56 (Allen et al. 1998)'],
        'data_date': date.today().isoformat(),
    }
