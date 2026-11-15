"""Farmer Tool Registry — controlled tools for the Farmer Agent (Phase 6).

Read tools wrap existing engines. Write tools (observation, task) are
mutating and require explicit user confirmation via ConfirmationRequired.
Every tool validates ownership through the request-scoped AgentContext.
"""
from datetime import date, timedelta

from core.services.nasa import fetch_power, search_collections
from core.services.climate import get_climate_indicators
from core.services.tools import Tool, ToolRegistry, ToolError

from ..models import Field, Farm, FarmTask, FarmObservation, CropCycle
from .daily import get_daily_briefing
from .irrigation import get_irrigation_advice
from .lifecycle import get_lifecycle
from .recommend import recommend_crops
from .risk import assess_field_risks
from .economics import get_economics
from .diagnosis import diagnose


def _get_field(params, context):
    fid = params.get('field_id') or getattr(context, 'active_field_id', None)
    if not fid:
        raise ToolError('field_id required')
    fl = Field.objects.filter(id=fid, farm__farmer=context.farmer).select_related('farm', 'current_crop').first()
    if fl is None:
        raise ToolError('field not found or not owned')
    return fl


def _get_farm(params, context):
    fid = params.get('farm_id') or getattr(context, 'active_farm_id', None)
    farm = Farm.objects.filter(id=fid, farmer=context.farmer).first() if fid else context.farmer.farms.first()
    if farm is None:
        raise ToolError('farm not found')
    return farm


def _active_cycle(field):
    return (CropCycle.objects.filter(field=field, status='active')
            .select_related('crop').order_by('-planting_date').first())


def _coords(field):
    if field.lat is None or field.lon is None:
        raise ToolError('field coordinates are required for weather/climate tools')
    return float(field.lat), float(field.lon)


def _power_summary(lat, lon, days):
    end = date.today()
    start = end - timedelta(days=max(1, min(int(days or 7), 30)))
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


def _t_daily(params, context):
    return get_daily_briefing(context.farmer)


def _t_weather(params, context):
    fl = _get_field(params, context)
    lat, lon = _coords(fl)
    return _power_summary(lat, lon, params.get('days', 7))


def _t_climate(params, context):
    fl = _get_field(params, context)
    lat, lon = _coords(fl)
    return get_climate_indicators(lat, lon)


def _t_irrigation(params, context):
    fl = _get_field(params, context)
    return get_irrigation_advice(fl)


def _t_crop_status(params, context):
    fl = _get_field(params, context)
    cycle = _active_cycle(fl)
    if cycle is None:
        return {'status': 'no_active_cycle', 'field': fl.name,
                'crop': fl.current_crop.key if fl.current_crop else None,
                'message_fa': 'چرخه کاشت فعالی برای این قطعه ثبت نشده است.'}
    life = get_lifecycle(cycle)
    stage = life.get('current_stage') or {}
    return {
        'status': 'ok', 'field': fl.name, 'cycle_id': cycle.id,
        'crop': life.get('crop'), 'crop_name_fa': life.get('crop_name_fa'),
        'planting_date': life.get('planting_date'), 'progress': life.get('progress'),
        'growth_stage': stage.get('name_fa'), 'current_stage': stage,
        'days_to_harvest': life.get('days_to_harvest'),
        'estimated_harvest': life.get('estimated_harvest'),
        'method': life.get('method'), 'confidence': life.get('confidence'),
        'data_sources': ['NASA POWER → GDD'],
        'limitations': ['بر اساس GDD واقعی؛ دقت به کامل بودن داده دما بستگی دارد.'],
    }


def _t_recommend(params, context):
    fl = _get_field(params, context)
    return recommend_crops(fl, top=int(params.get('top') or 5))


def _t_risks(params, context):
    fl = _get_field(params, context)
    return {'field_id': fl.id, 'field_name': fl.name, 'risks': assess_field_risks(fl)}


def _t_economics(params, context):
    farm = _get_farm(params, context)
    out = get_economics(
        farm,
        yield_kg_ha=params.get('yield_kg_ha'),
        price_per_unit=params.get('price_per_unit'),
        area_ha=params.get('area_ha'),
    )
    out['data_sources'] = ['FarmExpense', 'Field area']
    return out


def _t_tasks(params, context):
    qs = FarmTask.objects.filter(farmer=context.farmer).select_related('field').order_by('due_date', '-created_at')
    if params.get('field_id'):
        qs = qs.filter(field_id=params['field_id'])
    done = params.get('done')
    if done is True:
        qs = qs.filter(done=True)
    elif done is False or done is None:
        qs = qs.filter(done=False)
    limit = int(params.get('limit') or 20)
    return {'tasks': [{'id': t.id, 'title': t.title, 'done': t.done,
                       'due_date': t.due_date.isoformat() if t.due_date else None,
                       'field_id': t.field_id, 'field_name': t.field.name if t.field else None,
                       'source': t.source} for t in qs[:max(1, min(limit, 100))]]}


def _t_diagnose(params, context):
    fl = _get_field(params, context)
    symptoms = params.get('symptoms') or ''
    if isinstance(symptoms, str):
        import re
        symptoms = [s for s in re.split(r'[،,؛;]| و ', symptoms) if s.strip()]
    cycle = _active_cycle(fl)
    stage = None
    if cycle is not None:
        try:
            stage = (get_lifecycle(cycle).get('current_stage') or {}).get('name_fa')
        except Exception:
            stage = None
    return diagnose(symptoms, crop_name=cycle.crop.name_fa if cycle else None, stage=stage)


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


def _parse_due_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise ToolError('due_date must use YYYY-MM-DD')


def _t_create_observation(params, context):
    fl = _get_field(params, context)
    note = (params.get('note') or '').strip()
    if not note:
        raise ToolError('note required')
    obs = FarmObservation.objects.create(field=fl, note=note)
    return {'id': obs.id, 'field_id': fl.id, 'note': obs.note}


def _t_create_task(params, context):
    title = (params.get('title') or '').strip()
    if not title:
        raise ToolError('title required')
    fl = None
    if params.get('field_id') or getattr(context, 'active_field_id', None):
        fl = _get_field(params, context)
    task = FarmTask.objects.create(
        farmer=context.farmer, field=fl, title=title,
        due_date=_parse_due_date(params.get('due_date')), source='agent')
    return {'id': task.id, 'title': task.title, 'field_id': fl.id if fl else None}


_registry = None


def get_registry():
    global _registry
    if _registry is None:
        r = ToolRegistry()
        field_schema = {'field_id': {'type': 'number', 'required': False}}
        r.register(Tool('get_daily_briefing', 'Daily briefing for all fields',
                        _t_daily, permission='read'))
        r.register(Tool('get_weather', 'Recent weather for a field (NASA POWER)',
                        _t_weather, permission='read',
                        schema={**field_schema, 'days': {'type': 'number', 'required': False}}))
        r.register(Tool('get_climate', 'Climate indicators for a field',
                        _t_climate, permission='read', schema=field_schema))
        r.register(Tool('get_irrigation_status', 'Irrigation advice for a field',
                        _t_irrigation, permission='read', schema=field_schema))
        r.register(Tool('calculate_water_requirement', 'Water requirement calc',
                        _t_irrigation, permission='read', schema=field_schema))
        r.register(Tool('get_crop_status', 'Crop/lifecycle status',
                        _t_crop_status, permission='read', schema=field_schema))
        r.register(Tool('get_lifecycle_status', 'Crop lifecycle status',
                        _t_crop_status, permission='read', schema=field_schema))
        r.register(Tool('get_crop_recommendation', 'Crop recommendation',
                        _t_recommend, permission='read',
                        schema={**field_schema, 'top': {'type': 'number', 'required': False}}))
        r.register(Tool('get_active_risks', 'Risk assessment',
                        _t_risks, permission='read', schema=field_schema))
        r.register(Tool('get_farm_economics', 'Farm economics',
                        _t_economics, permission='read',
                        schema={'farm_id': {'type': 'number', 'required': False},
                                'yield_kg_ha': {'type': 'number', 'required': False},
                                'price_per_unit': {'type': 'number', 'required': False},
                                'area_ha': {'type': 'number', 'required': False}}))
        r.register(Tool('get_farm_tasks', 'Open farm tasks',
                        _t_tasks, permission='read',
                        schema={'field_id': {'type': 'number', 'required': False},
                                'done': {'type': 'bool', 'required': False},
                                'limit': {'type': 'number', 'required': False}}))
        r.register(Tool('diagnose_field', 'Diagnose field symptoms',
                        _t_diagnose, permission='read',
                        schema={'field_id': {'type': 'number', 'required': False},
                                'symptoms': {'type': 'string', 'required': False}}))
        r.register(Tool('get_scientific_datasets', 'Search NASA CMR catalog metadata',
                        _t_scientific_datasets, permission='read',
                        schema={'keyword': {'type': 'string', 'required': False},
                                'limit': {'type': 'number', 'required': False}}))
        r.register(Tool('create_observation', 'Record field observation',
                        _t_create_observation, permission='write', mutating=True,
                        schema={'field_id': {'type': 'number', 'required': False},
                                'note': {'type': 'string', 'required': True}}))
        r.register(Tool('create_farm_task', 'Create farm task',
                        _t_create_task, permission='write', mutating=True,
                        schema={'field_id': {'type': 'number', 'required': False},
                                'title': {'type': 'string', 'required': True},
                                'due_date': {'type': 'string', 'required': False}}))
        _registry = r
    return _registry
