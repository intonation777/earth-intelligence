"""Decision-support layer: combines NASA POWER weather with FAOSTAT trends.

Agronomic logic follows FAO-56 / standard crop-coefficient practice:
growing degree days (GDD), water balance (ET vs rainfall), frost and heat
stress day counts, dry-spell detection, humidity-related disease risk and
year-over-year comparison. Every recommendation is derived from real
fetched data and carries its source. No synthetic values are produced.
"""
from datetime import date, timedelta

from .nasa import fetch_power
from .fao import CROPS, fetch_crop

POWER_PARAMS = ['T2M', 'T2M_MAX', 'T2M_MIN', 'PRECTOTCORR', 'RH2M',
                'ALLSKY_SFC_SW_DWN', 'EVPTRNS', 'WS10M']

# FAO-56 inspired crop profiles:
#   tb    = base temperature (C); GDD accumulates above this
#   heat  = heat-stress threshold for daily Tmax (C)
#   frost = frost-damage threshold for daily Tmin (C)
#   gdd   = indicative seasonal GDD requirement to maturity
#   water = indicative seasonal water need (mm)
CROP_PROFILES = {
    'wheat':     {'tb': 0,  'heat': 32, 'frost': -2, 'gdd': 1400, 'water': 450},
    'barley':    {'tb': 0,  'heat': 30, 'frost': -4, 'gdd': 1200, 'water': 350},
    'rice':      {'tb': 10, 'heat': 38, 'frost':  5, 'gdd': 1800, 'water': 1200},
    'maize':     {'tb': 8,  'heat': 38, 'frost':  2, 'gdd': 1500, 'water': 600},
    'potato':    {'tb': 4,  'heat': 30, 'frost':  0, 'gdd': 1200, 'water': 500},
    'tomato':    {'tb': 10, 'heat': 35, 'frost':  5, 'gdd': 1100, 'water': 500},
    'sugarbeet': {'tb': 4,  'heat': 28, 'frost': -3, 'gdd': 1300, 'water': 550},
    'dates':     {'tb': 12, 'heat': 45, 'frost': -2, 'gdd': 2000, 'water': 900},
    'pistachio': {'tb': 8,  'heat': 40, 'frost': -5, 'gdd': 1600, 'water': 700},
}

WATER_NEED = {k: ('بالا' if v['water'] >= 700 else 'متوسط' if v['water'] >= 450 else 'کم')
              for k, v in CROP_PROFILES.items()}

LEVEL_FA = {'good': 'مناسب', 'info': 'اطلاع', 'warn': 'نیازمند توجه'}


def _series_map(power, code):
    for p in power.get('parameters', []):
        if p['code'] == code:
            return {pt['date']: pt['value'] for pt in p['points']}
    return {}


def _avg(values):
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def _sum(values):
    return sum(v for v in values if v is not None)


def _fao_trend(crop_key):
    """Return yield/production 5-year trend summary, or None if unavailable."""
    try:
        fao = fetch_crop(crop_key)
    except Exception:
        return None
    out = {}
    for metric in ('yield', 'production'):
        rows = [r for r in fao['series'].get(metric, []) if r.get('value')]
        if len(rows) >= 10:
            last5 = sum(r['value'] for r in rows[-5:]) / 5
            prev5 = sum(r['value'] for r in rows[-10:-5]) / 5
            pct = (last5 - prev5) / prev5 * 100 if prev5 else 0
            out[metric] = {
                'last5_avg': round(last5, 2),
                'prev5_avg': round(prev5, 2),
                'change_pct': round(pct, 1),
                'unit': rows[-1].get('unit', ''),
                'last_year': rows[-1]['year'],
            }
    return out or None


def _longest_dry_spell(rain_by_date, dates):
    """Longest run of consecutive days with rain < 1 mm. Missing data breaks the run."""
    best = cur = 0
    for d in dates:
        v = rain_by_date.get(d)
        if v is not None and v < 1.0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def _gdd(tmax_by_date, tmin_by_date, dates, base_temp):
    """Growing degree days: sum of max(0, (Tmax+Tmin)/2 - Tb) over the period."""
    total = 0.0
    n = 0
    for d in dates:
        tmax, tmin = tmax_by_date.get(d), tmin_by_date.get(d)
        if tmax is None or tmin is None:
            continue
        total += max(0.0, (tmax + tmin) / 2 - base_temp)
        n += 1
    return round(total, 1), n


def _drought_spi(lat, lon):
    """SPI-3/SPI-6 from 24 months of monthly NASA POWER precipitation.

    Reuses the Climate Engine's gamma-based SPI. Cached 12h per location.
    Returns None when insufficient months are available — never fabricates.
    """
    from django.core.cache import cache
    key = f'advice:spi:{round(float(lat), 2)}:{round(float(lon), 2)}'
    cached = cache.get(key)
    if cached is not None:
        return cached
    result = None
    try:
        end = date.today()
        start = end - timedelta(days=730)
        power = fetch_power(lat, lon, start.strftime('%Y%m%d'), end.strftime('%Y%m%d'),
                            ['PRECTOTCORR'], community='AG', temporal='monthly')
        pts = []
        for p in power.get('parameters', []):
            if p['code'] == 'PRECTOTCORR':
                pts = sorted(p['points'], key=lambda x: x['date'])
        series = [pt['value'] for pt in pts if pt['value'] is not None]
        if len(series) >= 12:
            from .climate import _spi_series
            spi3 = _spi_series(series, 3)
            spi6 = _spi_series(series, 6)
            result = {'spi_3m': spi3[-1] if spi3 else None,
                      'spi_6m': spi6[-1] if spi6 else None,
                      'months': len(series)}
    except Exception:
        result = None
    cache.set(key, result, 60 * 60 * 12)
    return result


def _yoy(lat, lon, start, end, params):
    """Same 30-day window one year earlier, for year-over-year comparison."""
    try:
        prev = fetch_power(lat, lon,
                           (start - timedelta(days=365)).strftime('%Y%m%d'),
                           (end - timedelta(days=365)).strftime('%Y%m%d'),
                           params, community='AG', temporal='daily')
    except Exception:
        return None
    pdates = prev.get('dates', [])
    if not pdates:
        return None
    t2m = _avg([v for p in prev.get('parameters', []) if p['code'] == 'T2M'
                for v in [pt['value'] for pt in p['points']]])
    rain = _sum([pt['value'] for p in prev.get('parameters', [])
                 if p['code'] == 'PRECTOTCORR' for pt in p['points']])
    return {'avg_temp_c': round(t2m, 1) if t2m is not None else None,
            'rain_total_mm': round(rain, 1), 'days': len(pdates)}


def get_advice(lat, lon, crop_key):
    crop = next((c for c in CROPS if c['key'] == crop_key), None)
    if not crop:
        raise ValueError('محصول انتخاب‌شده پشتیبانی نمی‌شود')
    profile = CROP_PROFILES.get(crop['key'], CROP_PROFILES['wheat'])

    end = date.today()
    start = end - timedelta(days=30)
    power = fetch_power(lat, lon, start.strftime('%Y%m%d'), end.strftime('%Y%m%d'),
                        POWER_PARAMS, community='AG', temporal='daily')

    maps = {c: _series_map(power, c) for c in POWER_PARAMS}
    dates = power.get('dates', [])

    def vals(code):
        return [maps[code].get(d) for d in dates]

    t2m = _avg(vals('T2M'))
    t2m_max = _avg(vals('T2M_MAX'))
    t2m_min = _avg(vals('T2M_MIN'))
    rain_vals = vals('PRECTOTCORR')
    rain_total = _sum(rain_vals)
    wet_days = sum(1 for v in rain_vals if v is not None and v >= 1.0)
    heavy_rain_days = sum(1 for v in rain_vals if v is not None and v >= 10.0)
    rh = _avg(vals('RH2M'))
    solar = _avg(vals('ALLSKY_SFC_SW_DWN'))
    et_vals = vals('EVPTRNS')
    et_total = _sum(et_vals)
    et = _avg(et_vals)
    wind_vals = vals('WS10M')
    spray_days = sum(1 for v in wind_vals if v is not None and v >= 4.0)

    # --- Agronomic indices ---
    gdd_total, gdd_days = _gdd(maps['T2M_MAX'], maps['T2M_MIN'], dates, profile['tb'])
    frost_days = sum(1 for v in vals('T2M_MIN') if v is not None and v <= profile['frost'])
    heat_days = sum(1 for v in vals('T2M_MAX') if v is not None and v >= profile['heat'])
    dry_spell = _longest_dry_spell(maps['PRECTOTCORR'], dates)
    water_deficit = et_total - rain_total if et_total else None

    if rh is not None and t2m is not None:
        if rh >= 75 and 15 <= t2m <= 30:
            disease_risk = 'high'
        elif rh >= 65:
            disease_risk = 'medium'
        else:
            disease_risk = 'low'
    else:
        disease_risk = None

    weather = {
        'days': len(dates),
        'avg_temp_c': round(t2m, 1) if t2m is not None else None,
        'max_temp_c': round(t2m_max, 1) if t2m_max is not None else None,
        'min_temp_c': round(t2m_min, 1) if t2m_min is not None else None,
        'rain_total_mm': round(rain_total, 1),
        'wet_days': wet_days,
        'heavy_rain_days': heavy_rain_days,
        'avg_humidity_pct': round(rh, 1) if rh is not None else None,
        'avg_solar_kwh': round(solar, 2) if solar is not None else None,
        'avg_et_mm_day': round(et, 2) if et is not None else None,
        'avg_wind_ms': round(_avg(wind_vals), 1) if _avg(wind_vals) is not None else None,
    }

    metrics = {
        'gdd_total': gdd_total,
        'gdd_per_day': round(gdd_total / gdd_days, 1) if gdd_days else None,
        'gdd_target': profile['gdd'],
        'gdd_pct_of_season': round(gdd_total / profile['gdd'] * 100, 1) if profile['gdd'] else None,
        'frost_days': frost_days,
        'heat_days': heat_days,
        'dry_spell_days': dry_spell,
        'water_deficit_mm': round(max(0.0, water_deficit), 1) if water_deficit is not None else None,
        'disease_risk': disease_risk,
        'spray_days': spray_days,
    }

    spi_ctx = _drought_spi(lat, lon)
    if spi_ctx:
        metrics['spi_3m'] = spi_ctx['spi_3m']
        metrics['spi_6m'] = spi_ctx['spi_6m']
        metrics['spi_months'] = spi_ctx['months']

    yoy = _yoy(lat, lon, start, end, POWER_PARAMS)
    if yoy and t2m is not None and yoy.get('avg_temp_c') is not None:
        yoy['temp_diff_c'] = round(t2m - yoy['avg_temp_c'], 1)
    if yoy and rain_total and yoy.get('rain_total_mm') is not None:
        if yoy['rain_total_mm'] >= 10:
            yoy['rain_diff_pct'] = round((rain_total - yoy['rain_total_mm']) / yoy['rain_total_mm'] * 100, 1)
        else:
            yoy['rain_diff_mm'] = round(rain_total - yoy['rain_total_mm'], 1)

    recs = []

    def add(level, title, detail, source='NASA POWER'):
        recs.append({'level': level, 'level_fa': LEVEL_FA[level],
                     'title': title, 'detail': detail, 'source': source})

    need = WATER_NEED.get(crop['key'], 'متوسط')

    # --- Water balance rules ---
    if rain_total < 10:
        add('warn', 'بارندگی این ناحیه بسیار کم است',
            f'در ۳۰ روز گذشته فقط {rain_total:.1f} میلی‌متر باران باریده و {wet_days} روز بارانی داشته‌ایم. '
            f'نیاز آبی {crop["name_fa"]} «{need}» است؛ آبیاری را جدی بگیرید.')
    elif rain_total < 40:
        add('info', 'بارندگی متوسط است',
            f'در ۳۰ روز گذشته {rain_total:.1f} میلی‌متر باران باریده است. '
            f'برای {crop["name_fa"]} (نیاز آبی {need}) آبیاری مکمل را فراموش نکنید.')
    else:
        add('good', 'بارندگی مناسب بوده است',
            f'{rain_total:.1f} میلی‌متر باران در ۳۰ روز گذشته؛ برای بیشتر محصولات دیم مناسب است.')

    if water_deficit is not None and water_deficit > 50:
        add('warn', 'کسری آب قابل‌توجه است',
            f'تبخیر و تعرق ({et_total:.0f} میلی‌متر) از بارش ({rain_total:.1f} میلی‌متر) {water_deficit:.0f} میلی‌متر بیشتر بوده؛ '
            'خاک در حال از دست دادن رطوبت است و آبیاری تکمیلی ضروری است.')
    elif water_deficit is not None and water_deficit > 0:
        add('info', 'کسری آب خفیف وجود دارد',
            f'تبخیر و تعرق حدود {water_deficit:.0f} میلی‌متر از بارش بیشتر بوده؛ آبیاری سبک در مراحل حساس توصیه می‌شود.')

    if dry_spell >= 15:
        add('warn', f'خشکسالی {dry_spell} روزه در ناحیه',
            f'طولانی‌ترین دوره بدون باران {dry_spell} روز بوده است. برای {crop["name_fa"]} آبیاری عمیق و مالچ‌پاشی را در نظر بگیرید.')
    elif dry_spell >= 8:
        add('info', f'دوره خشکی {dry_spell} روزه',
            f'طولانی‌ترین دوره بدون باران {dry_spell} روز بوده؛ رطوبت خاک را پایش کنید.')

    # --- Temperature / phenology rules ---
    if frost_days > 0:
        add('warn', f'{frost_days} روز یخبندان در دوره',
            f'{frost_days} روز دمای کمینه به آستانه سرمازدگی {crop["name_fa"]} ({profile["frost"]}°C) یا کمتر رسیده؛ '
            'از پوشش محافظ و آبیاری ضدیخ در شب‌های سرد استفاده کنید.')
    if heat_days >= 5:
        add('warn', f'{heat_days} روز گرمای شدید',
            f'{heat_days} روز دمای بیشینه از آستانه تنش حرارتی {crop["name_fa"]} ({profile["heat"]}°C) عبور کرده؛ '
            'گرده‌افشانی و پرشدن دانه ممکن است مختل شود.')
    elif heat_days > 0:
        add('info', f'{heat_days} روز گرمای قابل‌توجه',
            f'{heat_days} روز دمای بیشینه از {profile["heat"]}°C عبور کرده؛ آبیاری را به ساعات خنک موکول کنید.')

    if gdd_total and metrics['gdd_pct_of_season'] is not None:
        pct = metrics['gdd_pct_of_season']
        if pct < 20:
            lvl, msg = 'info', 'در ابتدای فصل رشد است'
        elif pct < 60:
            lvl, msg = 'good', 'در مرحله رشد فعال است'
        else:
            lvl, msg = 'info', 'به مرحله رسیدگی نزدیک می‌شود'
        add(lvl, f'رشد {crop["name_fa"]}: {gdd_total} درجه-روز (GDD)',
            f'در ۳۰ روز گذشته {gdd_total} درجه-روز انباشته شد (میانگین {metrics["gdd_per_day"]} در روز)؛ '
            f'این معادل {pct}% از نیاز فصل ({profile["gdd"]} GDD) است — {msg}.', source='NASA POWER · FAO-56')

    # --- Multi-month drought context (SPI from monthly POWER) ---
    if spi_ctx and spi_ctx.get('spi_6m') is not None:
        s6 = spi_ctx['spi_6m']
        s3 = spi_ctx.get('spi_3m')
        if s6 <= -1.5:
            add('warn', 'خشکسالی متوسط تا شدید در ۶ ماه اخیر',
                f'شاخص SPI-6 = {s6} (مقیاس ۶ ماهه، {spi_ctx["months"]} ماه داده ماهانه NASA POWER)؛ '
                f'بارش ۶ ماه اخیر به‌طور معناداری زیر نرمال است. برای {crop["name_fa"]} برنامه آبیاری را بر اساس کم‌آبی تنظیم کنید.',
                source='NASA POWER monthly · SPI-6')
        elif s6 <= -1.0:
            add('info', 'خشکسالی خفیف در ۶ ماه اخیر',
                f'شاخص SPI-6 = {s6}؛ بارش کمی زیر نرمال است. پایش رطوبت خاک و آبیاری به‌موقع توصیه می‌شود.',
                source='NASA POWER monthly · SPI-6')
        elif s6 >= 1.5:
            add('info', 'بارش بالاتر از نرمال در ۶ ماه اخیر',
                f'شاخص SPI-6 = {s6}؛ رطوبت بالا خطر بیماری‌های قارچی را افزایش می‌دهد — تهویه canopy را جدی بگیرید.',
                source='NASA POWER monthly · SPI-6')
        if s3 is not None and s3 <= -1.5 and s6 > -1.5:
            add('warn', 'خشکسالی در ۳ ماه اخیر تشدید شده',
                f'SPI-3 = {s3} در حالی که SPI-6 = {s6}؛ خشکسالی اخیرتر از میانگین ۶ ماهه است — فوریت آبیاری بیشتر است.',
                source='NASA POWER monthly · SPI-3')

    # --- Humidity / disease risk ---
    susceptible = crop['key'] in ('tomato', 'potato', 'rice', 'wheat')
    if disease_risk == 'high' and susceptible:
        add('warn', 'خطر بیماری‌های قارچی بالاست',
            f'رطوبت نسبی {rh:.0f}٪ با دمای {t2m:.0f}°C برای {crop["name_fa"]} شرایط مساعد بیماری‌های قارچی است؛ '
            'تهویه canopy و فاصله‌گذاری مناسب را رعایت کنید.')
    elif disease_risk == 'high':
        add('info', 'رطوبت بالا — پایش بیماری',
            f'رطوبت نسبی {rh:.0f}٪ بالاست؛ در صورت مشاهده علائم بیماری در مزرعه اقدام کنید.')

    # --- Wind / spraying ---
    if spray_days >= 5:
        add('info', f'{spray_days} روز باد برای سم‌پاشی نامناسب',
            f'در {spray_days} روز سرعت باد از ۴ متر بر ثانیه بیشتر بوده؛ سم‌پاشی را به ساعات آرام‌تر موکول کنید.')

    if heavy_rain_days >= 3:
        add('info', f'{heavy_rain_days} روز باران شدید',
            f'{heavy_rain_days} روز بارش بالای ۱۰ میلی‌متر ثبت شد؛ از فرسایش خاک و آب‌گرفتگی ریشه‌ها جلوگیری کنید.')

    # --- Solar / drying rule ---
    if solar is not None and solar >= 5:
        add('good', 'تابش خورشیدی مناسب برای خشک‌کردن محصول',
            f'میانگین تابش {solar:.2f} کیلووات‌ساعت بر مترمربع در روز؛ شرایط برای خشک‌کردن محصول در آفتاب فراهم است.')

    # --- Year-over-year comparison ---
    if yoy:
        parts = []
        if yoy.get('temp_diff_c') is not None:
            parts.append(f'دما {"گرم‌تر" if yoy["temp_diff_c"] > 0 else "سردتر" if yoy["temp_diff_c"] < 0 else "مشابه"} از پارسال ({yoy["temp_diff_c"]:+.1f}°C)')
        if yoy.get('rain_diff_pct') is not None:
            parts.append(f'بارش {"بیشتر" if yoy["rain_diff_pct"] > 0 else "کمتر"} از پارسال ({yoy["rain_diff_pct"]:+.0f}٪)')
        elif yoy.get('rain_diff_mm') is not None:
            parts.append(f'بارش {"بیشتر" if yoy["rain_diff_mm"] > 0 else "کمتر"} از پارسال ({yoy["rain_diff_mm"]:+.1f} mm)')
        if parts:
            add('info', 'مقایسه با همین دوره پارسال', ' · '.join(parts) + '.', source='NASA POWER')

    # --- FAOSTAT national trend ---
    trend = _fao_trend(crop_key)
    if trend and 'yield' in trend:
        y = trend['yield']
        if y['change_pct'] > 3:
            add('good', f'روند عملکرد {crop["name_fa"]} در ایران صعودی است',
                f'میانگین ۵ سال اخیر {y["last5_avg"]} {y["unit"]} در برابر {y["prev5_avg"]} {y["unit"]} دوره قبل '
                f'({y["change_pct"]:+.1f}٪).', source='FAOSTAT')
        elif y['change_pct'] < -3:
            add('info', f'روند عملکرد {crop["name_fa"]} در ایران کمی کاهش یافته',
                f'میانگین ۵ سال اخیر {y["last5_avg"]} {y["unit"]} در برابر {y["prev5_avg"]} {y["unit"]} دوره قبل '
                f'({y["change_pct"]:+.1f}٪).', source='FAOSTAT')
        else:
            add('info', f'روند عملکرد {crop["name_fa"]} در ایران نسبتاً پایدار است',
                f'میانگین ۵ سال اخیر {y["last5_avg"]} {y["unit"]} ({y["change_pct"]:+.1f}٪ نسبت به دوره قبل).',
                source='FAOSTAT')

    # --- Crop-specific tip ---
    tips = {
        'rice': 'برنج به آب فراوان نیاز دارد؛ از کاشت در زمین‌های با سطح آب زیرین کم خودداری کنید.',
        'maize': 'ذرت در مرحله گرده‌افشانی به رطوبت کافی خاک نیاز دارد؛ تنش آبی در این مرحله عملکرد را به‌شدت کاهش می‌دهد.',
        'wheat': 'گندم در مرحله ساقه‌رفتن به فسفر و در مرحله دانه‌پرشدن به آب کافی نیاز دارد.',
        'dates': 'خرما به خشکی مقاوم است اما در فصل گرده‌افشانی (بهار) به رطوبت کافی نیاز دارد.',
        'pistachio': 'پسته درختی مقاوم است؛ آبیاری عمیق و کم‌تکرار بهتر از آبیاری سطحی مکرر است.',
        'barley': 'جو نسبت به گندم به خشکی و شوری مقاوم‌تر است و برای کشت دیم مناسب‌تر است.',
        'potato': 'سیب‌زمینی به خاک سبک و زهکشی خوب نیاز دارد؛ از کاشت در زمین‌های سنگین خودداری کنید.',
        'tomato': 'گوجه‌فرنگی به آبیاری منظم و حذف علف‌های هرز نیاز دارد؛ آبیاری نابرابر باعث ترک‌خوردگی می‌شود.',
        'sugarbeet': 'چغندرقند به خاک عمیق و حاصلخیز نیاز دارد؛ از کوددهی بیش از حد نیتروژن خودداری کنید.',
    }
    add('info', f'نکته اختصاصی {crop["name_fa"]}', tips.get(crop['key'], ''))

    return {
        'source': 'NASA POWER + FAOSTAT',
        'location': {'lat': float(lat), 'lon': float(lon)},
        'crop': crop,
        'period': {'start': start.isoformat(), 'end': end.isoformat(), 'days': len(dates)},
        'weather': weather,
        'metrics': metrics,
        'yoy': yoy,
        'fao_trend': trend,
        'recommendations': recs,
        'disclaimer': 'این پیشنهادها بر اساس داده‌های واقعی ۳۰ روز گذشته، مقایسه با دوره مشابه پارسال و آمار ملی FAOSTAT تولید شده‌اند و بر مبنای روش‌های استاندارد FAO-56 (درجه-روز رشد، توازن آب، تنش سرما/گرما) محاسبه شده‌اند؛ جایگزین مشاوره کارشناس محلی نیستند.',
    }
