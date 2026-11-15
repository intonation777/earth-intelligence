"""Crop Recommendation Engine — ranks crops for a field using real data.

Criteria (all from real sources, no synthetic data):
- Climate: NASA POWER monthly T2M/PRECTOTCORR (12 months) + SPI-6 drought index
- Soil: field soil_type / salinity (user input)
- Water: field water_source / irrigation_method (user input)
- Crop params: CropProfile (FAO-56 references)

Every recommendation carries score, reasons, limitations, data sources
and confidence. Missing data → lower confidence, never guessing.
"""
from datetime import date

from core.services.climate import get_climate_indicators
from ..models import CropProfile

SEASON_BY_MONTH = {12: 'winter', 1: 'winter', 2: 'winter', 3: 'spring', 4: 'spring',
                   5: 'spring', 6: 'summer', 7: 'summer', 8: 'summer', 9: 'autumn',
                   10: 'autumn', 11: 'autumn'}

SOIL_MATCH = {'clay': ['clay', 'loam'], 'loam': ['loam', 'clay', 'sandy'],
              'sandy': ['sandy', 'loam'], 'silty': ['loam', 'clay'], 'saline': ['saline', 'sandy']}

SALINITY_RANK = {'low': 0, 'medium': 1, 'high': 2}
CROP_SALINITY_RANK = {'low': 0, 'medium': 1, 'high': 2}


def _monthly_climate(lat, lon):
    """Aggregate daily POWER data into monthly climate via the Climate Engine
    (single cached call — same source as SPI/SPEI)."""
    if lat is None or lon is None or not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return {'tmean': None, 'tmax': None, 'tmin': None, 'rain': None,
                'error': 'مختصات نامعتبر — آب‌وهوا محاسبه نشد'}
    d = get_climate_indicators(lat, lon)
    monthly = d.get('monthly') or []
    tmeans = [m['tmean_c'] for m in monthly if m.get('tmean_c') is not None]
    tmaxs = [m['tmax_c'] for m in monthly if m.get('tmax_c') is not None]
    tmins = [m['tmin_c'] for m in monthly if m.get('tmin_c') is not None]
    rains = [m['precip_mm'] for m in monthly if m.get('precip_mm') is not None]
    return {'tmean': sum(tmeans) / len(tmeans) if tmeans else None,
            'tmax': sum(tmaxs) / len(tmaxs) if tmaxs else None,
            'tmin': sum(tmins) / len(tmins) if tmins else None,
            'rain_total': sum(rains) if rains else None,
            'months': len(monthly)}


def _score_crop(crop, climate, field, spi6):
    """Return (score 0-100, reasons[], limitations[], confidence)."""
    score = 50.0
    reasons, limits = [], []
    conf = 0.5

    # --- temperature fit ---
    tmean, tmax, tmin = climate['tmean'], climate['tmax'], climate['tmin']
    if tmean is not None and crop.t_max_c is not None and tmax is not None:
        if tmax > crop.t_max_c + 5:
            score -= 20; limits.append(f'دمای بیشینه مشاهده‌شده ({tmax:.0f}°C) بالاتر از تحمل محصول ({crop.t_max_c}°C) است')
        elif tmax > crop.t_max_c:
            score -= 8; reasons.append('دمای بیشینه نزدیک به حد بالای محصول است')
        else:
            score += 10; reasons.append('دمای منطقه در محدوده مناسب محصول است')
    if tmin is not None and crop.t_min_c is not None and tmin < crop.t_min_c - 3:
        score -= 15; limits.append(f'دمای کمینه ({tmin:.0f}°C) زیر حد تحمل محصول ({crop.t_min_c}°C) است')
    conf += 0.1 if tmean is not None else 0

    # --- water need vs rainfall + source ---
    rain = climate['rain_total']
    water = field.water_source or ''
    irr = field.irrigation_method or ''
    if crop.water_need_mm is not None:
        if water == 'rainfed' or irr == 'rainfed':
            if rain is not None and rain < crop.water_need_mm * 0.5:
                score -= 25; limits.append(f'محصول نیاز آبی {crop.water_need_mm}mm دارد ولی بارش سالانه ~{rain:.0f}mm است — دیم مناسب نیست')
            elif rain is not None:
                score += 5; reasons.append('نیاز آبی محصول با بارش دیم تا حدی تأمین می‌شود')
        elif water in ('well', 'qanat', 'river') or irr in ('drip', 'sprinkler', 'flood', 'furrow'):
            score += 8; reasons.append('منبع آب/روش آبیاری برای نیاز محصول کافی است')
        if rain is not None and crop.water_need_mm > rain * 1.5 and water == 'rainfed':
            score -= 10
    conf += 0.1 if rain is not None else 0

    # --- drought risk (SPI-6) ---
    if spi6 is not None and crop.water_need_mm is not None:
        if spi6 <= -1.5 and crop.water_need_mm > 600:
            score -= 15; limits.append(f'خشکسالی متوسط (SPI-6={spi6:.1f}) — محصول پرآب در معرض تنش است')
        elif spi6 <= -1.0 and crop.water_need_mm > 600:
            score -= 7; reasons.append('خشکسالی خفیف — محصول پرآب نیازمند آبیاری تکمیلی است')
        elif spi6 >= 0:
            score += 3

    # --- soil match ---
    soil = field.soil_type or ''
    if soil and crop.soil_preference:
        prefs = SOIL_MATCH.get(soil, [soil])
        if crop.soil_preference in prefs:
            score += 8; reasons.append(f'خاک {soil} با ترجیح محصول ({crop.soil_preference}) سازگار است')
        else:
            score -= 6; limits.append(f'خاک {soil} با ترجیح محصول ({crop.soil_preference}) کمتر سازگار است')

    # --- salinity ---
    sal = field.salinity or ''
    if sal and crop.salinity_tolerance:
        if SALINITY_RANK.get(sal, 0) > CROP_SALINITY_RANK.get(crop.salinity_tolerance, 0):
            score -= 12; limits.append(f'شوری {sal} بالاتر از تحمل محصول ({crop.salinity_tolerance}) است')
        elif SALINITY_RANK.get(sal, 0) <= CROP_SALINITY_RANK.get(crop.salinity_tolerance, 0):
            score += 5; reasons.append('تحمل شوری محصول با وضعیت زمین سازگار است')

    # --- planting season ---
    month = date.today().month
    season = SEASON_BY_MONTH.get(month)
    seasons = crop.planting_seasons or []
    if seasons and 'perennial' not in seasons:
        if season in seasons:
            score += 10; reasons.append(f'فصل کاشت فعلی ({season}) برای این محصول مناسب است')
        else:
            score -= 8; limits.append(f'فصل کاشت فعلی ({season}) خارج از فصل‌های مناسب محصول است')

    score = max(0, min(100, score))
    return score, reasons, limits, min(0.95, conf)


def recommend_crops(field, top=10):
    """Rank all crops for a Field. Returns dict with ranking + metadata."""
    if field.lat is None or field.lon is None:
        return {'error': 'مختصات زمین (lat/lon) برای توصیه محصول لازم است', 'ranking': []}

    climate = _monthly_climate(field.lat, field.lon)
    spi6 = None
    try:
        d = get_climate_indicators(field.lat, field.lon)
        spi6 = d['indicators'].get('spi_6m', {}).get('value')
    except Exception:
        pass
    # _monthly_climate already calls get_climate_indicators (cached) — reuse

    results = []
    for crop in CropProfile.objects.all():
        score, reasons, limits, conf = _score_crop(crop, climate, field, spi6)
        results.append({
            'crop': crop.key, 'name_fa': crop.name_fa, 'name_en': crop.name_en,
            'score': round(score, 1),
            'water_need_mm': crop.water_need_mm, 'growth_days': crop.growth_days,
            'kc_max': crop.kc_max, 'gdd_total': crop.gdd_total,
            'reasons_fa': reasons, 'limitations_fa': limits,
            'confidence': round(conf, 2),
        })
    results.sort(key=lambda r: -r['score'])
    return {
        'field': {'id': field.id, 'name': field.name, 'lat': field.lat, 'lon': field.lon,
                  'soil_type': field.soil_type, 'salinity': field.salinity,
                  'water_source': field.water_source, 'irrigation_method': field.irrigation_method},
        'climate': climate, 'spi_6m': spi6,
        'ranking': results[:top], 'total_crops': len(results),
        'data_sources': ['NASA POWER (monthly T2M/PRECTOTCORR)', 'NASA POWER (daily→monthly SPI-6)',
                         'CropProfile (FAO-56 references)', 'Field input (user)'],
        'limitations': [
            'رتبه‌بندی بر اساس داده‌های اقلیمی ۱۲ ماه اخیر و ورودی کاربر است؛ داده خاک آزمایشگاهی (pH، بافت دقیق) در صورت وجود دقت را افزایش می‌دهد.',
            'قیمت فروش و هزینه تولید در این نسخه لحاظ نشده — در فاز اقتصاد اضافه می‌شود.',
            'این توصیه جایگزین نظر کارشناس کشاورزی نیست.',
        ],
    }
