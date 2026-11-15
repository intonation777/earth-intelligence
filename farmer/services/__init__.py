"""Auth + serialization helpers for farmer APIs.

Access control: every farmer-owned resource requires the owner's api_key
via `X-Farmer-Key` header or `?key=` query param. This is a lightweight
identity layer; full session auth can be added later without changing
the API contract.
"""
import json

from django.conf import settings
from django.http import JsonResponse

from ..models import FarmerProfile, Farm, Field, CropProfile


def _demo_farmer(request):
    """Public-demo mode: anonymous visitors get an isolated demo farmer account.

    Enabled only when settings.PUBLIC_DEMO is true (Render demo deployment).
    Each browser session receives its own FarmerProfile so demo data never
    mixes between visitors and no real user data is exposed.
    """
    if not getattr(settings, 'PUBLIC_DEMO', False):
        return None
    if not hasattr(request, 'session'):
        return None
    fid = request.session.get('farmer_id')
    if fid:
        return FarmerProfile.objects.filter(id=fid).first()
    import uuid
    demo = FarmerProfile.objects.create(
        name='Demo Visitor',
        login=f'demo-{uuid.uuid4().hex[:12]}@demo.local',
        is_active=True,
    )
    request.session['farmer_id'] = demo.id
    request.session.set_expiry(60 * 60 * 24)
    return demo


def get_farmer(request):
    # 1) session auth (preferred — survives api_key rotation)
    fid = request.session.get('farmer_id') if hasattr(request, 'session') else None
    if fid:
        f = FarmerProfile.objects.filter(id=fid).first()
        if f:
            return f
    # 2) api_key header/query (mobile apps, backward compat)
    key = request.headers.get('X-Farmer-Key') or request.GET.get('key') or ''
    if not key:
        return _demo_farmer(request)
    farmer = FarmerProfile.objects.filter(api_key=key).first()
    return farmer if farmer is not None else _demo_farmer(request)


def require_farmer(view):
    """Decorator: inject request.farmer or return 401."""
    def wrapper(request, *args, **kwargs):
        farmer = get_farmer(request)
        if farmer is None:
            return JsonResponse({'error': 'احراز هویت نامعتبر — X-Farmer-Key لازم است'}, status=401)
        request.farmer = farmer
        return view(request, *args, **kwargs)
    wrapper.__name__ = view.__name__
    return wrapper


def json_body(request):
    try:
        return json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return None


def farmer_to_dict(f):
    return {'id': f.id, 'name': f.name, 'phone': f.phone, 'login': f.login,
            'has_account': bool(f.password_hash), 'is_active': f.is_active,
            'api_key': f.api_key, 'created_at': f.created_at.isoformat()}


def farm_to_dict(fm):
    return {'id': fm.id, 'name': fm.name, 'province': fm.province,
            'fields_count': fm.fields.count(), 'created_at': fm.created_at.isoformat()}


def field_to_dict(fl):
    return {'id': fl.id, 'farm_id': fl.farm_id, 'name': fl.name,
            'lat': fl.lat, 'lon': fl.lon, 'area_ha': fl.area_ha,
            'soil_type': fl.soil_type, 'salinity': fl.salinity,
            'water_source': fl.water_source, 'irrigation_method': fl.irrigation_method,
            'slope': fl.slope, 'current_crop': fl.current_crop.key if fl.current_crop else None,
            'planting_date': fl.planting_date.isoformat() if fl.planting_date else None}


def crop_to_dict(c):
    return {'key': c.key, 'name_fa': c.name_fa, 'name_en': c.name_en,
            'base_temp_c': c.base_temp_c, 't_min_c': c.t_min_c, 't_max_c': c.t_max_c,
            'gdd_total': c.gdd_total, 'water_need_mm': c.water_need_mm,
            'kc_max': c.kc_max, 'growth_days': c.growth_days,
            'planting_seasons': c.planting_seasons, 'soil_preference': c.soil_preference,
            'salinity_tolerance': c.salinity_tolerance}


def get_owned_field(farmer, field_id):
    return Field.objects.filter(id=field_id, farm__farmer=farmer).first()


def get_owned_farm(farmer, farm_id):
    return Farm.objects.filter(id=farm_id, farmer=farmer).first()
