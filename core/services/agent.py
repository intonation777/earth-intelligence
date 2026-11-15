"""Hybrid AI Engine — rule-based intent router over real data services.

No external LLM is called: the engine parses the user's question with
explicit Persian/English keyword patterns, selects the correct data
sources, runs the scientific pipeline and returns an explainable answer
with sources, confidence and limitations. When the intent or location
cannot be determined, it asks — it never guesses.
"""
import re
from datetime import date, timedelta

from .geocode import search_places
from .climate import get_climate_indicators
from .advice import get_advice
from .fao import fetch_crop, CROPS
from .nasa import fetch_power
from .agent_intents import resolve_intent
from .science_tools import get_science_registry
from .tools import AgentContext, ToolError

CROP_ALIASES = {
    'wheat': ['گندم', 'wheat'], 'barley': ['جو', 'barley'], 'rice': ['برنج', 'شلتوک', 'rice'],
    'maize': ['ذرت', 'maize', 'corn'], 'potato': ['سیب‌زمینی', 'potato'],
    'tomato': ['گوجه', 'tomato'], 'sugarbeet': ['چغندر', 'sugarbeet', 'sugar beet'],
    'dates': ['خرما', 'date', 'dates'], 'pistachio': ['پسته', 'pistachio'],
}

INTENTS = [
    ('drought', ['خشکسالی', 'خشک', 'drought', 'spi', 'spei', 'کم‌آبی', 'کم ابی', 'dry spell']),
    ('crop_advice', ['محصول', 'آبیاری', 'کاشت', 'برداشت', 'مشاور', 'crop', 'irrigation', 'planting', 'harvest', 'farm']),
    ('temperature', ['دما', 'temperature', 'گرما', 'سرما', 'heatwave', 'فrost', 'یخبندان', 'hot', 'cold']),
    ('vegetation', ['ndvi', 'evi', 'پوشش گیاهی', 'vegetation', 'سنجش از دور', 'remote sensing', 'ماهواره']),
    ('production', ['تولید', 'عملکرد', 'production', 'yield', 'fao', 'آمار کشاورزی']),
    ('weather', ['هوا', 'باران', 'بارش', 'weather', 'rain', 'precipitation', 'پیش‌بینی']),
]


def _detect_intent(text):
    t = text.lower()
    scores = {}
    for intent, keywords in INTENTS:
        score = sum(1 for k in keywords if k in t)
        if score:
            scores[intent] = score
    if not scores:
        return None, 0.0
    best = max(scores, key=scores.get)
    total = sum(scores.values())
    return best, round(scores[best] / total, 2)


def _detect_crop(text):
    t = text.lower()
    for key, aliases in CROP_ALIASES.items():
        if any(a in t for a in aliases):
            return key
    return None


def _resolve_location(text, lat, lon):
    """Return (lat, lon, place_name) — explicit coords win, else geocode."""
    if lat is not None and lon is not None:
        return float(lat), float(lon), None
    # strip common question words to improve geocoding
    cleaned = re.sub(r'(در|of|in|at|برای|about|لطفا|please|؟|\?)', ' ', text, flags=re.I)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    tokens = cleaned.split()
    candidates = []
    for n in (2, 1, 3, len(tokens)):
        cand = ' '.join(tokens[-n:]) if n <= len(tokens) else cleaned
        if len(cand) >= 3 and cand not in candidates:
            candidates.append(cand)
    for tok in reversed(tokens):  # mid-sentence place names
        if len(tok) >= 3 and tok not in candidates:
            candidates.append(tok)
    import time
    for i, candidate in enumerate(candidates):
        if i:
            time.sleep(1.1)  # Nominatim: 1 req/s
        try:
            items = search_places(candidate)
        except Exception:
            items = []
        if items:
            top = items[0]
            return float(top['lat']), float(top['lon']), top.get('display_name', candidate)
    return None, None, None


def _fmt(v, nd=1):
    return '—' if v is None else (f'{v:.{nd}f}' if isinstance(v, float) else str(v))


def _answer_scientific_catalog(q, canonical, resolved):
    """Read-only CMR catalog search for scientific/satellite intents."""
    ctx = AgentContext(owner_key='public-observatory', read_only=True)
    try:
        out = get_science_registry().run(
            'get_scientific_datasets', {'keyword': q[:120], 'limit': 5}, context=ctx)
        result = out.get('result', {})
    except ToolError as e:
        return {'intent': canonical, 'resolved_intent': canonical,
                'confidence': resolved.get('confidence'),
                'answer_fa': f'جستجوی کاتالوگ ناموفق بود: {e}',
                'data_sources': ['NASA Earthdata CMR'],
                'limitations': ['Catalog metadata only — not downloaded data values.']}
    items = result.get('items', [])
    if items:
        titles = '؛ '.join((i.get('title') or i.get('short_name') or '')[:80] for i in items[:3])
        ans = (f'{len(items)} مجموعه داده مرتبط در CMR پیدا شد: {titles}. '
               'این‌ها متادیتای کاتالوگ هستند، نه داده پردازش‌شده.')
    else:
        ans = ('در کاتالوگ CMR نتیجه‌ای برای این عبارت پیدا نشد؛ داده ساختگی ارائه نمی‌شود. '
               'از بخش Catalog در داشبورد برای جستجوی دقیق‌تر استفاده کنید.')
    return {'intent': canonical, 'resolved_intent': canonical,
            'confidence': resolved.get('confidence'), 'answer_fa': ans,
            'data': {'items': items, 'hits': result.get('hits')},
            'data_sources': ['NASA Earthdata CMR'],
            'limitations': result.get('limitations', ['Catalog metadata only — not downloaded data values.'])}


def answer_question(question, lat=None, lon=None, crop=None):
    """Route a natural-language question to the right data pipeline."""
    q = (question or '').strip()
    if len(q) < 3:
        return {'error': 'سؤال خیلی کوتاه است — لطفاً سؤال کامل‌تری بپرسید.'}

    resolved = resolve_intent(q)
    canonical = resolved.get('intent')
    intent, confidence = _detect_intent(q)
    if canonical in ('satellite_search', 'scientific_research') and intent is None:
        return _answer_scientific_catalog(q, canonical, resolved)
    if intent is None:
        return {
            'intent': 'unknown', 'resolved_intent': canonical, 'confidence': 0.0,
            'audience': 'expert',
            'answer_fa': 'متوجه سؤال شما نشدم. می‌توانید درباره خشکسالی (SPI/SPEI)، دما و امواج گرما، '
                         'وضعیت محصول و آبیاری، پوشش گیاهی (NDVI/EVI)، تولید و عملکرد محصولات (FAO) '
                         'یا وضعیت هوا بپرسید.',
            'data_sources': [], 'limitations': ['سؤال خارج از دامنه داده‌های موجود است.'],
        }

    crop_key = crop or _detect_crop(q)
    la, lo, place = _resolve_location(q, lat, lon)

    base = {'intent': intent, 'resolved_intent': canonical, 'confidence': confidence,
            'audience': 'expert', 'place': place,
            'location': {'lat': la, 'lon': lo} if la is not None else None}

    # --- intents that need a location ---
    if intent in ('drought', 'temperature', 'weather', 'crop_advice') and la is None:
        base.update({
            'answer_fa': 'برای پاسخ به این سؤال به موقعیت مکانی نیاز دارم. '
                         'نام شهر/روستا را در سؤال بنویسید (مثلاً «وضعیت گندم در شیراز») یا مختصات را مشخص کنید.',
            'data_sources': [], 'limitations': ['موقعیت مکانی مشخص نشد.'],
        })
        return base

    try:
        if intent == 'drought':
            d = get_climate_indicators(la, lo)
            ind = d['indicators']
            spi6 = ind.get('spi_6m', {}).get('value')
            spi3 = ind.get('spi_3m', {}).get('value')
            spei6 = ind.get('spei_6m', {}).get('value')
            wb = ind.get('water_balance', {}).get('value')
            verdict = ('خشکسالی متوسط تا شدید' if spi6 is not None and spi6 <= -1.5
                       else 'خشکسالی خفیف' if spi6 is not None and spi6 <= -1.0
                       else 'وضعیت نرمال تا مرطوب' if spi6 is not None and spi6 >= -1.0
                       else 'نامشخص')
            base.update({
                'answer_fa': f'وضعیت خشکسالی در {place or f"{la:.2f}، {lo:.2f}"}: {verdict}. '
                             f'SPI-6 = {_fmt(spi6)}، SPI-3 = {_fmt(spi3)}، SPEI-6 = {_fmt(spei6)}، '
                             f'تراز آب دوره = {_fmt(wb)} میلی‌متر. '
                             f'دوره تحلیل: {d["period"]["start"]} تا {d["period"]["end"]} ({d["period"]["months"]} ماه).',
                'data': {'spi_3m': spi3, 'spi_6m': spi6, 'spei_6m': spei6,
                         'water_balance_mm': wb, 'period': d['period']},
                'data_sources': ['NASA POWER (daily→monthly)', 'SPI/SPEI engine'],
                'limitations': d.get('limitations', []),
            })
        elif intent == 'temperature':
            d = get_climate_indicators(la, lo)
            ind = d['indicators']
            hw = ind.get('heatwave', {}).get('value', {})
            frost = ind.get('frost_days', {}).get('value')
            anom = ind.get('temperature_anomaly_c', {}).get('value')
            base.update({
                'answer_fa': f'وضعیت دما در {place or f"{la:.2f}، {lo:.2f}"}: '
                             f'آنومالی دما (۱۲ ماه اخیر) = {_fmt(anom)}°C، '
                             f'روزهای ≥۳۵°C = {hw.get("days_ge35c", "—")}، '
                             f'رویدادهای امواج گرما = {hw.get("events_ge3days", "—")}، '
                             f'روزهای یخبندان = {_fmt(frost)}.',
                'data': {'temp_anomaly_c': anom, 'heatwave': hw, 'frost_days': frost,
                         'period': d['period']},
                'data_sources': ['NASA POWER T2M/T2M_MAX/T2M_MIN'],
                'limitations': d.get('limitations', []),
            })
        elif intent == 'weather':
            end = date.today()
            start = end - timedelta(days=30)
            power = fetch_power(la, lo, start.strftime('%Y%m%d'), end.strftime('%Y%m%d'),
                                ['T2M', 'PRECTOTCORR', 'RH2M'], community='AG', temporal='daily')
            maps = {}
            for p in power.get('parameters', []):
                maps[p['code']] = [pt['value'] for pt in p['points'] if pt['value'] is not None]
            t2m = maps.get('T2M', [])
            rain = maps.get('PRECTOTCORR', [])
            rh = maps.get('RH2M', [])
            avg_t = sum(t2m) / len(t2m) if t2m else None
            tot_rain = sum(rain) if rain else None
            avg_rh = sum(rh) / len(rh) if rh else None
            base.update({
                'answer_fa': f'وضعیت ۳۰ روز گذشته در {place or f"{la:.2f}، {lo:.2f}"}: '
                             f'میانگین دما {_fmt(avg_t)}°C، مجموع بارش {_fmt(tot_rain)} میلی‌متر، '
                             f'میانگین رطوبت {_fmt(avg_rh)}٪.',
                'data': {'avg_temp_c': avg_t, 'rain_total_mm': tot_rain, 'avg_humidity_pct': avg_rh,
                         'days': len(power.get('dates', []))},
                'data_sources': ['NASA POWER (daily, 30 days)'],
                'limitations': ['فقط ۳۰ روز گذشته؛ برای روند بلندمدت از موتور اقلیم استفاده کنید.'],
            })
        elif intent == 'crop_advice':
            ck = crop_key or 'wheat'
            crop_obj = next((c for c in CROPS if c['key'] == ck), None)
            if not crop_obj:
                base.update({'answer_fa': 'محصول مشخصی تشخیص داده نشد؛ نام محصول را بنویسید.',
                             'data_sources': [], 'limitations': []})
                return base
            d = get_advice(la, lo, ck)
            recs = d.get('recommendations', [])
            top = recs[:3]
            base.update({
                'answer_fa': f'توصیه برای {crop_obj["name_fa"]} در {place or f"{la:.2f}، {lo:.2f}"}: '
                             + ' | '.join(f'{r["level_fa"]}: {r["title"]}' for r in top)
                             + f'. ({len(recs)} توصیه کل — جزئیات در تب مشاور کشاورز)',
                'data': {'crop': crop_obj['name_fa'], 'metrics': d.get('metrics', {}),
                         'weather': d.get('weather', {}),
                         'top_recommendations': top},
                'data_sources': ['NASA POWER (30d daily + 24m monthly)', 'FAOSTAT', 'SPI engine'],
                'limitations': ['توصیه‌ها rule-based کشاورزی هستند، نه تشخیص هوش مصنوعی.'],
            })
        elif intent == 'vegetation':
            base.update({
                'answer_fa': 'برای پایش پوشش گیاهی از لایه‌های ماهواره‌ای NASA GIBS استفاده کنید: '
                             'NDVI (۸ روزه)، EVI (۸/۱۶ روزه)، NDVI ماهانه و رطوبت خاک SMAP — همه در تب «نمای کلی» '
                             'با انتخاب تاریخ و امکان مقایسه دو تاریخ. داده‌ها واقعی و با تأخیر چندروزه منتشر می‌شوند.',
                'data': {'layers': ['MODIS_Terra_NDVI_8Day', 'MODIS_Terra_EVI_8Day',
                                    'MODIS_Terra_L3_NDVI_Monthly', 'MODIS_Aqua_L3_EVI_16Day',
                                    'SMAP_L3_Passive_Day_Soil_Moisture']},
                'data_sources': ['NASA GIBS WMTS'],
                'limitations': ['محاسبه کمی NDVI/EVI از باندهای خام نیازمند دانلود گرانول و rasterio است (نصب‌نشده).'],
            })
        elif intent == 'production':
            ck = crop_key or 'wheat'
            crop_obj = next((c for c in CROPS if c['key'] == ck), None)
            if not crop_obj:
                base.update({'answer_fa': 'محصول مشخصی تشخیص داده نشد.', 'data_sources': [], 'limitations': []})
                return base
            try:
                d = fetch_crop(ck)
                y = d['series'].get('yield', [])
                p = d['series'].get('production', [])
                last_y = y[-1] if y else None
                last_p = p[-1] if p else None
                base.update({
                    'answer_fa': f'آخرین داده رسمی FAOSTAT برای {crop_obj["name_fa"]} ({d["area"]}): '
                                 f'عملکرد {last_y["value"] if last_y else "—"} {last_y["unit"] if last_y else ""} '
                                 f'({last_y["year"] if last_y else "—"})، تولید {last_p["value"] if last_p else "—"} '
                                 f'{last_p["unit"] if last_p else ""} ({last_p["year"] if last_p else "—"}). '
                                 f'برای رتبه‌بندی جهانی از تب FAO استفاده کنید.',
                    'data': {'crop': crop_obj['name_fa'], 'last_yield': last_y, 'last_production': last_p},
                    'data_sources': ['FAOSTAT QCL'],
                    'limitations': ['داده سالانه رسمی؛ برای مقایسه جهانی از بخش «مقایسه جهانی» استفاده کنید.'],
                })
            except Exception as e:
                base.update({'answer_fa': f'دریافت داده FAOSTAT ناموفق بود: {e}. داده ساختگی ارائه نمی‌شود.',
                             'data_sources': ['FAOSTAT QCL'], 'limitations': ['API فاو در دسترس نیست.']})
        else:
            base.update({'answer_fa': 'این سؤال پشتیبانی نمی‌شود.', 'data_sources': [], 'limitations': []})
    except Exception as e:
        base.update({'answer_fa': f'خطا در پردازش سؤال: {e}', 'data_sources': [],
                     'limitations': ['خطای داخلی — لطفاً دوباره تلاش کنید.']})
    return base
