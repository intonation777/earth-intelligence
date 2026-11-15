"""Earth Intelligence tool registry — read-only scientific tools (Phase 6).

These tools wrap existing NASA/FAOSTAT services. No tool writes to the
database or executes raw SQL; all outputs are validated as JSON-safe.
"""
from datetime import date, timedelta

from core.services.tools import Tool, ToolRegistry, ToolError
from .nasa import fetch_power, search_collections
from .climate import get_climate_indicators
from .fao import fetch_crop, CROPS


def _coords(params):
    lat, lon = params.get('lat'), params.get('lon')
    if lat is None or lon is None:
        raise ToolError('lat and lon are required')
    return float(lat), float(lon)


def _t_weather(params, context):
    lat, lon = _coords(params)
    days = int(params.get('days') or 7)
    end = date.today()
    start = end - timedelta(days=max(1, min(days, 30)))
    power = fetch_power(lat, lon, start.strftime('%Y%m%d'), end.strftime('%Y%m%d'),
                        ['T2M', 'PRECTOTCORR', 'RH2M'], community='AG', temporal='daily')
    maps = {}
    for p in power.get('parameters', []):
        maps[p['code']] = [pt['value'] for pt in p['points'] if pt['value'] is not None]
    t2m, rain, rh = maps.get('T2M', []), maps.get('PRECTOTCORR', []), maps.get('RH2M', [])
    return {
        'days': len(power.get('dates', [])),
        'avg_temp_c': round(sum(t2m) / len(t2m), 1) if t2m else None,
        'rain_total_mm': round(sum(rain), 1) if rain else None,
        'avg_humidity_pct': round(sum(rh) / len(rh), 1) if rh else None,
        'data_sources': ['NASA POWER (daily)'],
        'limitations': ['Point/grid meteorological estimate — not a direct field measurement.'],
    }


def _t_climate(params, context):
    lat, lon = _coords(params)
    return get_climate_indicators(lat, lon)


def _t_scientific_datasets(params, context):
    keyword = (params.get('keyword') or '').strip()
    limit = int(params.get('limit') or 5)
    result = search_collections(keyword=keyword, page_size=max(1, min(limit, 10)))
    return {
        'source': result.get('source'), 'hits': result.get('hits'),
        'items': result.get('items', [])[:max(1, min(limit, 10))],
        'data_sources': ['NASA Earthdata CMR'],
        'limitations': ['Catalog metadata only — not downloaded data values.'],
    }


def _t_crop_production(params, context):
    key = (params.get('crop') or '').strip()
    crop = next((c for c in CROPS if c['key'] == key), None)
    if crop is None:
        raise ToolError('unknown crop')
    d = fetch_crop(key)
    y = d.get('series', {}).get('yield', [])
    p = d.get('series', {}).get('production', [])
    return {'crop': crop.get('name_fa'), 'area': d.get('area'),
            'last_yield': y[-1] if y else None, 'last_production': p[-1] if p else None,
            'data_sources': ['FAOSTAT QCL'],
            'limitations': ['Annual official statistics; not field-level yield.']}


_registry = None


def get_science_registry():
    global _registry
    if _registry is None:
        r = ToolRegistry()
        r.register(Tool('get_weather', 'Recent weather summary (NASA POWER)',
                        _t_weather, permission='read',
                        schema={'lat': {'type': 'number', 'required': True},
                                'lon': {'type': 'number', 'required': True},
                                'days': {'type': 'number', 'required': False}}))
        r.register(Tool('get_climate', 'Climate indicators (SPI/SPEI/heatwave)',
                        _t_climate, permission='read',
                        schema={'lat': {'type': 'number', 'required': True},
                                'lon': {'type': 'number', 'required': True}}))
        r.register(Tool('get_scientific_datasets', 'Search NASA CMR catalog metadata',
                        _t_scientific_datasets, permission='read',
                        schema={'keyword': {'type': 'string', 'required': False},
                                'limit': {'type': 'number', 'required': False}}))
        r.register(Tool('get_crop_production', 'FAOSTAT crop production/yield',
                        _t_crop_production, permission='read',
                        schema={'crop': {'type': 'string', 'required': True}}))
        _registry = r
    return _registry
