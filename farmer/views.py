"""Farmer APIs — Phase 2 foundation: profile, farms, fields, crops."""
import json

from django.contrib.auth.hashers import make_password, check_password
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .models import FarmerProfile, Farm, Field, CropProfile
from core.services.throttle import rate_limit
from .services import (require_farmer, json_body, farmer_to_dict, farm_to_dict, get_farmer,
                       field_to_dict, crop_to_dict, get_owned_farm, get_owned_field)


@csrf_exempt
@require_POST
def profile_create(request):
    """ثبت‌نام کشاورز — api_key خودکار تولید می‌شود."""
    data = json_body(request)
    if data is None:
        return JsonResponse({'error': 'JSON نامعتبر'}, status=400)
    name = (data.get('name') or '').strip()
    if not name:
        return JsonResponse({'error': 'نام کشاورز الزامی است'}, status=400)
    f = FarmerProfile.objects.create(name=name, phone=(data.get('phone') or '').strip())
    return JsonResponse({'farmer': farmer_to_dict(f)}, status=201)


@csrf_exempt
@require_POST
@rate_limit(5, 60, 'farmer-register')
def farmer_register(request):
    """Real account registration — login (email/phone) + password.

    Keeps api_key for backward compatibility, but adds session-capable
    credentials. Existing profile_create remains for guest/api-key use.
    """
    data = json_body(request)
    if data is None:
        return JsonResponse({'error': 'JSON نامعتبر'}, status=400)
    name = (data.get('name') or '').strip()
    login = (data.get('login') or data.get('email') or data.get('phone') or '').strip()
    password = data.get('password') or ''
    if not name:
        return JsonResponse({'error': 'نام کشاورز الزامی است'}, status=400)
    if not login:
        return JsonResponse({'error': 'ایمیل یا شماره موبایل الزامی است'}, status=400)
    if len(password) < 8:
        return JsonResponse({'error': 'رمز عبور باید حداقل ۸ کاراکتر باشد'}, status=400)
    login_norm = login.lower() if '@' in login else login
    if FarmerProfile.objects.filter(login__iexact=login_norm).exists():
        return JsonResponse({'error': 'این حساب قبلاً ثبت شده است'}, status=409)
    f = FarmerProfile.objects.create(
        name=name, phone=(data.get('phone') or (login if '@' not in login else '')).strip(),
        login=login_norm, password_hash=make_password(password), is_active=True)
    request.session['farmer_id'] = f.id
    request.session.set_expiry(60 * 60 * 24 * 30)
    return JsonResponse({'ok': True, 'farmer': farmer_to_dict(f)}, status=201)


@require_GET
@require_farmer
def profile_get(request):
    return JsonResponse({'farmer': farmer_to_dict(request.farmer)})


@csrf_exempt
@require_POST
@require_farmer
def farm_create(request):
    data = json_body(request)
    if data is None:
        return JsonResponse({'error': 'JSON نامعتبر'}, status=400)
    name = (data.get('name') or '').strip()
    if not name:
        return JsonResponse({'error': 'نام مزرعه الزامی است'}, status=400)
    fm = Farm.objects.create(farmer=request.farmer, name=name,
                             province=(data.get('province') or '').strip())
    return JsonResponse({'farm': farm_to_dict(fm)}, status=201)


@require_GET
@require_farmer
def farm_list(request):
    farms = Farm.objects.filter(farmer=request.farmer).prefetch_related('fields')
    return JsonResponse({'farms': [farm_to_dict(f) for f in farms]})


def _valid_coords(lat, lon):
    """Return (lat, lon) or raise ValueError if out of range."""
    if lat is None or lon is None:
        return lat, lon
    lat, lon = float(lat), float(lon)
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        raise ValueError('مختصات نامعتبر')
    return lat, lon


@csrf_exempt
@require_POST
@require_farmer
def field_create(request):
    data = json_body(request)
    if data is None:
        return JsonResponse({'error': 'JSON نامعتبر'}, status=400)
    farm = get_owned_farm(request.farmer, data.get('farm_id'))
    if farm is None:
        return JsonResponse({'error': 'مزرعه یافت نشد'}, status=404)
    name = (data.get('name') or '').strip()
    if not name:
        return JsonResponse({'error': 'نام قطعه زمین الزامی است'}, status=400)
    try:
        lat, lon = _valid_coords(data.get('lat'), data.get('lon'))
    except (ValueError, TypeError):
        return JsonResponse({'error': 'مختصات نامعتبر — عرض باید -90 تا 90 و طول -180 تا 180 باشد'}, status=400)
    crop = None
    if data.get('current_crop'):
        crop = CropProfile.objects.filter(key=data['current_crop']).first()
    fl = Field.objects.create(
        farm=farm, name=name,
        lat=lat, lon=lon, area_ha=data.get('area_ha'),
        soil_type=data.get('soil_type', ''), salinity=data.get('salinity', ''),
        water_source=data.get('water_source', ''), irrigation_method=data.get('irrigation_method', ''),
        slope=data.get('slope', ''), current_crop=crop,
        planting_date=data.get('planting_date') or None)
    return JsonResponse({'field': field_to_dict(fl)}, status=201)


@require_GET
@require_farmer
def field_list(request):
    farm_id = request.GET.get('farm_id')
    qs = Field.objects.filter(farm__farmer=request.farmer).select_related('farm', 'current_crop')
    if farm_id:
        qs = qs.filter(farm_id=farm_id)
    return JsonResponse({'fields': [field_to_dict(f) for f in qs]})


@require_GET
@require_farmer
def field_detail(request, field_id):
    fl = get_owned_field(request.farmer, field_id)
    if fl is None:
        return JsonResponse({'error': 'قطعه زمین یافت نشد'}, status=404)
    return JsonResponse({'field': field_to_dict(fl)})


@csrf_exempt
@require_POST
@require_farmer
def field_update(request, field_id):
    """به‌روزرسانی تدریجی — فقط فیلدهای ارسال‌شده تغییر می‌کنند."""
    fl = get_owned_field(request.farmer, field_id)
    if fl is None:
        return JsonResponse({'error': 'قطعه زمین یافت نشد'}, status=404)
    data = json_body(request)
    if data is None:
        return JsonResponse({'error': 'JSON نامعتبر'}, status=400)
    if 'lat' in data or 'lon' in data:
        try:
            _valid_coords(data.get('lat', fl.lat), data.get('lon', fl.lon))
        except (ValueError, TypeError):
            return JsonResponse({'error': 'مختصات نامعتبر'}, status=400)
    numeric = {'lat', 'lon', 'area_ha', 'planting_date'}
    allowed = ['name', 'lat', 'lon', 'area_ha', 'soil_type', 'salinity',
               'water_source', 'irrigation_method', 'slope', 'planting_date']
    for k in allowed:
        if k in data:
            v = data[k]
            setattr(fl, k, (v if v not in ('', None) else None) if k in numeric else (v or ''))
    if 'current_crop' in data:
        fl.current_crop = CropProfile.objects.filter(key=data['current_crop']).first() if data['current_crop'] else None
    fl.save()
    return JsonResponse({'field': field_to_dict(fl)})


@require_GET
def crop_list(request):
    crops = CropProfile.objects.all().order_by('key')
    return JsonResponse({'crops': [crop_to_dict(c) for c in crops],
                         'count': crops.count()})


@require_GET
@require_farmer
@rate_limit(20, 60, 'farmer-crop-recommend')
def crop_recommend(request):
    """رتبه‌بندی محصولات برای یک قطعه زمین — field_id یا lat/lon+soil."""
    from .services.recommend import recommend_crops
    field_id = request.GET.get('field_id')
    if field_id:
        fl = get_owned_field(request.farmer, field_id)
        if fl is None:
            return JsonResponse({'error': 'قطعه زمین یافت نشد'}, status=404)
        return JsonResponse(recommend_crops(fl))
    # ad-hoc: lat/lon + soil params without a saved field
    lat, lon = request.GET.get('lat'), request.GET.get('lon')
    if lat is None or lon is None:
        return JsonResponse({'error': 'field_id یا lat/lon لازم است'}, status=400)
    try:
        lat, lon = float(lat), float(lon)
    except ValueError:
        return JsonResponse({'error': 'lat/lon نامعتبر'}, status=400)
    from .models import Field
    tmp = Field(farm=None, name='ad-hoc', lat=lat, lon=lon,
                soil_type=request.GET.get('soil_type', ''),
                salinity=request.GET.get('salinity', ''),
                water_source=request.GET.get('water_source', ''),
                irrigation_method=request.GET.get('irrigation_method', ''))
    return JsonResponse(recommend_crops(tmp))


@csrf_exempt
@require_POST
@require_farmer
def cycle_create(request):
    """ایجاد چرخه کاشت برای یک قطعه."""
    from .models import CropCycle
    data = json_body(request)
    if data is None:
        return JsonResponse({'error': 'JSON نامعتبر'}, status=400)
    fl = get_owned_field(request.farmer, data.get('field_id'))
    if fl is None:
        return JsonResponse({'error': 'قطعه زمین یافت نشد'}, status=404)
    crop = CropProfile.objects.filter(key=data.get('crop')).first()
    if crop is None:
        return JsonResponse({'error': 'محصول نامعتبر'}, status=400)
    planting = data.get('planting_date')
    if not planting:
        return JsonResponse({'error': 'تاریخ کاشت الزامی است'}, status=400)
    from datetime import date as _date
    try:
        planting = _date.fromisoformat(planting)
    except ValueError:
        return JsonResponse({'error': 'فرمت تاریخ نامعتبر (YYYY-MM-DD)'}, status=400)
    cycle = CropCycle.objects.create(field=fl, crop=crop, planting_date=planting)
    return JsonResponse({'cycle': {'id': cycle.id, 'field_id': fl.id, 'crop': crop.key,
                                   'planting_date': planting.isoformat()}}, status=201)


@require_GET
@require_farmer
def cycle_list(request):
    from .models import CropCycle
    qs = CropCycle.objects.filter(field__farm__farmer=request.farmer).select_related('crop', 'field')
    return JsonResponse({'cycles': [{'id': c.id, 'field_id': c.field_id, 'field_name': c.field.name,
                                     'crop': c.crop.key, 'crop_name_fa': c.crop.name_fa,
                                     'planting_date': c.planting_date.isoformat(),
                                     'status': c.status} for c in qs]})


@require_GET
@require_farmer
def lifecycle_calendar(request):
    """تقویم چرخه کاشت — cycle_id یا field_id (آخرین چرخه فعال)."""
    from .models import CropCycle
    from .services.lifecycle import get_lifecycle
    cycle_id = request.GET.get('cycle_id')
    if cycle_id:
        cycle = CropCycle.objects.filter(id=cycle_id, field__farm__farmer=request.farmer).select_related('crop', 'field').first()
    else:
        field_id = request.GET.get('field_id')
        if not field_id:
            return JsonResponse({'error': 'cycle_id یا field_id لازم است'}, status=400)
        cycle = CropCycle.objects.filter(field_id=field_id, field__farm__farmer=request.farmer,
                                         status='active').select_related('crop', 'field').order_by('-planting_date').first()
    if cycle is None:
        return JsonResponse({'error': 'چرخه کاشت یافت نشد'}, status=404)
    return JsonResponse(get_lifecycle(cycle))


@require_GET
@require_farmer
@rate_limit(20, 60, 'farmer-irrigation')
def irrigation_advice(request):
    """توصیه آبیاری برای یک قطعه — field_id."""
    from .services.irrigation import get_irrigation_advice
    field_id = request.GET.get('field_id')
    if not field_id:
        return JsonResponse({'error': 'field_id لازم است'}, status=400)
    fl = get_owned_field(request.farmer, field_id)
    if fl is None:
        return JsonResponse({'error': 'قطعه زمین یافت نشد'}, status=404)
    return JsonResponse(get_irrigation_advice(fl))


@require_GET
@require_farmer
@rate_limit(20, 60, 'farmer-daily')
def daily_briefing(request):
    """«امروز در مزرعه چه کار کنم؟» — تجمیع همه موتورها."""
    from .services.daily import get_daily_briefing
    return JsonResponse(get_daily_briefing(request.farmer))


@csrf_exempt
@require_POST
@require_farmer
def task_create(request):
    from .models import FarmTask
    data = json_body(request)
    if data is None:
        return JsonResponse({'error': 'JSON نامعتبر'}, status=400)
    title = (data.get('title') or '').strip()
    if not title:
        return JsonResponse({'error': 'عنوان کار الزامی است'}, status=400)
    field = None
    if data.get('field_id'):
        field = get_owned_field(request.farmer, data['field_id'])
        if field is None:
            return JsonResponse({'error': 'قطعه زمین یافت نشد'}, status=404)
    due = data.get('due_date')
    if due:
        from datetime import date as _d
        try:
            due = _d.fromisoformat(due)
        except ValueError:
            return JsonResponse({'error': 'فرمت تاریخ نامعتبر'}, status=400)
    t = FarmTask.objects.create(farmer=request.farmer, field=field, title=title,
                                due_date=due, source=data.get('source', 'manual'))
    return JsonResponse({'task': {'id': t.id, 'title': t.title,
                                  'due_date': t.due_date.isoformat() if t.due_date else None}}, status=201)


@require_GET
@require_farmer
def task_list(request):
    from .models import FarmTask
    qs = FarmTask.objects.filter(farmer=request.farmer).select_related('field').order_by('done', 'due_date')
    return JsonResponse({'tasks': [{'id': t.id, 'title': t.title, 'done': t.done,
                                    'field_name': t.field.name if t.field else None,
                                    'due_date': t.due_date.isoformat() if t.due_date else None,
                                    'source': t.source} for t in qs]})


@csrf_exempt
@require_POST
@require_farmer
def task_done(request, task_id):
    from .models import FarmTask
    from django.utils import timezone
    t = FarmTask.objects.filter(id=task_id, farmer=request.farmer).first()
    if t is None:
        return JsonResponse({'error': 'کار یافت نشد'}, status=404)
    t.done = True
    t.done_at = timezone.now()
    t.save()
    return JsonResponse({'task': {'id': t.id, 'done': True}})


@require_GET
@require_farmer
@rate_limit(20, 60, 'farmer-risks')
def risk_list(request):
    """ارزیابی ریسک برای یک قطعه یا همه قطعات کشاورز."""
    from .services.risk import assess_field_risks
    field_id = request.GET.get('field_id')
    if field_id:
        fl = get_owned_field(request.farmer, field_id)
        if fl is None:
            return JsonResponse({'error': 'قطعه زمین یافت نشد'}, status=404)
        return JsonResponse({'field_id': fl.id, 'field_name': fl.name,
                             'risks': assess_field_risks(fl)})
    fields = Field.objects.filter(farm__farmer=request.farmer)
    out = []
    for fl in fields:
        risks = assess_field_risks(fl)
        if risks:
            out.append({'field_id': fl.id, 'field_name': fl.name, 'risks': risks})
    return JsonResponse({'fields': out})


@csrf_exempt
@require_POST
@require_farmer
@rate_limit(10, 60, 'farmer-observe')
def observe_upload(request):
    """بارگذاری تصویر گیاه — ذخیره به‌عنوان FarmObservation."""
    from .services.diagnosis import save_observation
    field_id = request.POST.get('field_id')
    fl = get_owned_field(request.farmer, field_id) if field_id else None
    if fl is None:
        return JsonResponse({'error': 'قطعه زمین یافت نشد'}, status=404)
    upload = request.FILES.get('image')
    if upload is None:
        return JsonResponse({'error': 'فایل تصویر الزامی است'}, status=400)
    obs, err = save_observation(fl, upload, request.POST.get('note', ''))
    if err:
        return JsonResponse({'error': err}, status=400)
    return JsonResponse({'observation': {'id': obs.id, 'field_id': fl.id,
                                         'note': obs.note}}, status=201)


@csrf_exempt
@require_POST
@require_farmer
@rate_limit(10, 60, 'farmer-diagnose')
def diagnose_symptoms(request):
    """تشخیص محافظه‌کارانه بر اساس علائم متنی."""
    from .services.diagnosis import diagnose
    data = json_body(request)
    if data is None:
        return JsonResponse({'error': 'JSON نامعتبر'}, status=400)
    symptoms = data.get('symptoms', [])
    if isinstance(symptoms, str):
        symptoms = [symptoms]
    crop_name = data.get('crop_name')
    stage = data.get('stage')
    return JsonResponse(diagnose(symptoms, crop_name=crop_name, stage=stage))


@require_GET
@require_farmer
def economics_view(request):
    """اقتصاد مزرعه — farm_id + yield_kg_ha + price_per_unit (اختیاری)."""
    from .services.economics import get_economics
    farm_id = request.GET.get('farm_id')
    if not farm_id:
        return JsonResponse({'error': 'farm_id لازم است'}, status=400)
    farm = get_owned_farm(request.farmer, farm_id)
    if farm is None:
        return JsonResponse({'error': 'مزرعه یافت نشد'}, status=404)
    y = request.GET.get('yield_kg_ha')
    p = request.GET.get('price')
    a = request.GET.get('area_ha')
    try:
        y = float(y) if y else None
        p = float(p) if p else None
        a = float(a) if a else None
    except ValueError:
        return JsonResponse({'error': 'پارامترهای عددی نامعتبر'}, status=400)
    return JsonResponse(get_economics(farm, yield_kg_ha=y, price_per_unit=p, area_ha=a))


@csrf_exempt
@require_POST
@require_farmer
def expense_create(request):
    from .models import FarmExpense
    data = json_body(request)
    if data is None:
        return JsonResponse({'error': 'JSON نامعتبر'}, status=400)
    farm = get_owned_farm(request.farmer, data.get('farm_id'))
    if farm is None:
        return JsonResponse({'error': 'مزرعه یافت نشد'}, status=404)
    amount = data.get('amount')
    if amount is None:
        return JsonResponse({'error': 'مبلغ الزامی است'}, status=400)
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'مبلغ نامعتبر'}, status=400)
    date_str = data.get('date')
    if date_str:
        from datetime import date as _d
        try:
            date_str = _d.fromisoformat(date_str)
        except ValueError:
            return JsonResponse({'error': 'فرمت تاریخ نامعتبر'}, status=400)
    else:
        from datetime import date as _d
        date_str = _d.today()
    e = FarmExpense.objects.create(
        farm=farm, date=date_str, category=data.get('category', 'other'),
        amount=amount, currency=data.get('currency', 'IRT'),
        notes=data.get('notes', ''))
    return JsonResponse({'expense': {'id': e.id, 'category': e.category,
                                     'amount': e.amount}}, status=201)


@require_GET
@require_farmer
def expense_list(request):
    from .models import FarmExpense
    farm_id = request.GET.get('farm_id')
    qs = FarmExpense.objects.filter(farm__farmer=request.farmer).select_related('farm')
    if farm_id:
        qs = qs.filter(farm_id=farm_id)
    return JsonResponse({'expenses': [{'id': e.id, 'farm_id': e.farm_id, 'date': e.date.isoformat(),
                                       'category': e.category, 'amount': e.amount,
                                       'currency': e.currency} for e in qs.order_by('-date')]})


@csrf_exempt
@require_POST
@require_farmer
@rate_limit(10, 60, 'farmer-agent')
def farmer_agent_view(request):
    """دستیار هوشمند کشاورز — سؤال → موتور مناسب → پاسخ ساده."""
    from .services.farmer_agent import answer
    data = json_body(request)
    if data is None:
        return JsonResponse({'error': 'JSON نامعتبر'}, status=400)
    q = data.get('question') or data.get('q') or ''
    fid = data.get('field_id')
    try:
        fid = int(fid) if fid else None
    except (TypeError, ValueError):
        fid = None
    return JsonResponse(answer(request.farmer, q, field_id=fid,
                                mode=data.get('mode') or 'simple'))


@csrf_exempt
@require_POST
@require_farmer
def operation_create(request):
    """ثبت عملیات مزرعه — irrigation | fertilizer | observation."""
    from .models import IrrigationRecord, FertilizerRecord, FarmObservation
    from datetime import date as _date
    data = json_body(request)
    if data is None:
        return JsonResponse({'error': 'JSON نامعتبر'}, status=400)
    op = data.get('type')
    field = get_owned_field(request.farmer, data.get('field_id'))
    if field is None:
        return JsonResponse({'error': 'قطعه زمین یافت نشد'}, status=404)
    d = data.get('date')
    try:
        d = _date.fromisoformat(d) if d else _date.today()
    except ValueError:
        return JsonResponse({'error': 'فرمت تاریخ نامعتبر'}, status=400)
    if op == 'irrigation':
        r = IrrigationRecord.objects.create(
            field=field, date=d,
            amount_m3=data.get('amount_m3'), duration_min=data.get('duration_min'),
            method=(data.get('method') or '').strip(), notes=(data.get('notes') or '').strip())
        return JsonResponse({'record': {'id': r.id, 'type': 'irrigation'}}, status=201)
    if op == 'fertilizer':
        r = FertilizerRecord.objects.create(
            field=field, date=d, kind=(data.get('kind') or '').strip(),
            amount_kg=data.get('amount_kg'), notes=(data.get('notes') or '').strip())
        return JsonResponse({'record': {'id': r.id, 'type': 'fertilizer'}}, status=201)
    if op == 'observation':
        r = FarmObservation.objects.create(field=field, note=(data.get('note') or '').strip())
        return JsonResponse({'record': {'id': r.id, 'type': 'observation'}}, status=201)
    return JsonResponse({'error': 'نوع عملیات نامعتبر — irrigation/fertilizer/observation'}, status=400)


@require_GET
@require_farmer
@rate_limit(10, 60, 'farmer-recommendations')
def recommendations_view(request):
    """Decision Engine — generate + list explainable recommendations."""
    from .services.decision import generate_recommendations, list_recommendations
    field_id = request.GET.get('field_id')
    if request.GET.get('generate', '1') != '0':
        gen = generate_recommendations(request.farmer, field_id)
        return JsonResponse(gen)
    return JsonResponse({'recommendations': list_recommendations(
        request.farmer, status=request.GET.get('status'), field_id=field_id)})


@csrf_exempt
@require_POST
@require_farmer
def recommendation_feedback(request, rec_id):
    """Feedback loop — accepted/rejected/completed/ignored + outcome."""
    from .services.decision import record_feedback
    data = json_body(request)
    if data is None:
        return JsonResponse({'error': 'JSON نامعتبر'}, status=400)
    rec = record_feedback(request.farmer, rec_id, data.get('status'),
                          data.get('outcome_note', ''), data.get('outcome_metrics'))
    if rec is None:
        return JsonResponse({'error': 'توصیه یافت نشد یا وضعیت نامعتبر'}, status=404)
    return JsonResponse({'recommendation': rec})


@require_GET
@require_farmer
def alerts_view(request):
    """Persisted risk alerts — list with unread count."""
    from .models import RiskAlert
    qs = RiskAlert.objects.filter(farmer=request.farmer, dismissed=False).select_related('field')
    if request.GET.get('unread') == '1':
        qs = qs.filter(is_read=False)
    if request.GET.get('status'):
        qs = qs.filter(status=request.GET['status'])
    if request.GET.get('severity'):
        qs = qs.filter(severity=request.GET['severity'])
    if request.GET.get('farm_id'):
        qs = qs.filter(field__farm_id=request.GET['farm_id'])
    items = [{'id': a.id, 'kind': a.kind, 'severity': a.severity,
              'title_fa': a.title_fa, 'detail_fa': a.detail_fa,
              'field_name': a.field.name if a.field else None,
              'farm_name': a.field.farm.name if a.field else None,
              'source': a.source, 'is_read': a.is_read, 'status': a.status,
              'evidence': a.evidence, 'expires_at': a.expires_at.isoformat() if a.expires_at else None,
              'created_at': a.created_at.isoformat(),
              'updated_at': a.updated_at.isoformat()} for a in qs[:100]]
    unread = RiskAlert.objects.filter(farmer=request.farmer, dismissed=False, is_read=False).count()
    counts = {s: RiskAlert.objects.filter(farmer=request.farmer, dismissed=False, status=s).count()
              for s in ('new', 'active', 'acknowledged', 'snoozed', 'resolved', 'expired')}
    return JsonResponse({'alerts': items, 'unread': unread, 'status_counts': counts})


@require_GET
@require_farmer
def alert_detail(request, alert_id):
    """Single alert detail."""
    from .models import RiskAlert
    try:
        a = RiskAlert.objects.select_related('field__farm').get(id=alert_id, farmer=request.farmer)
    except RiskAlert.DoesNotExist:
        return JsonResponse({'error': 'هشدار یافت نشد'}, status=404)
    return JsonResponse({'alert': {'id': a.id, 'kind': a.kind, 'severity': a.severity,
        'title_fa': a.title_fa, 'detail_fa': a.detail_fa,
        'field_name': a.field.name if a.field else None,
        'farm_name': a.field.farm.name if a.field else None,
        'source': a.source, 'is_read': a.is_read, 'dismissed': a.dismissed,
        'status': a.status, 'evidence': a.evidence,
        'expires_at': a.expires_at.isoformat() if a.expires_at else None,
        'acknowledged_at': a.acknowledged_at.isoformat() if a.acknowledged_at else None,
        'resolved_at': a.resolved_at.isoformat() if a.resolved_at else None,
        'created_at': a.created_at.isoformat(), 'updated_at': a.updated_at.isoformat()}})


@csrf_exempt
@require_POST
@require_farmer
def alert_action(request, alert_id):
    """Mark alert read or dismiss it."""
    from .models import RiskAlert
    data = json_body(request)
    if data is None:
        return JsonResponse({'error': 'JSON نامعتبر'}, status=400)
    try:
        a = RiskAlert.objects.get(id=alert_id, farmer=request.farmer)
    except RiskAlert.DoesNotExist:
        return JsonResponse({'error': 'هشدار یافت نشد'}, status=404)
    action = data.get('action')
    from django.utils import timezone
    if action == 'read':
        a.is_read = True
    elif action == 'dismiss':
        a.dismissed = True
    elif action == 'unread':
        a.is_read = False
    elif action == 'acknowledge':
        a.status = 'acknowledged'
        a.acknowledged_at = timezone.now()
        a.is_read = True
    elif action == 'snooze':
        a.status = 'snoozed'
        a.is_read = True
    elif action == 'resolve':
        a.status = 'resolved'
        a.resolved_at = timezone.now()
        a.is_read = True
    elif action == 'reactivate':
        a.status = 'active'
        a.resolved_at = None
    else:
        return JsonResponse({'error': 'action نامعتبر — read/dismiss/unread/acknowledge/snooze/resolve/reactivate'}, status=400)
    a.save()
    return JsonResponse({'alert': {'id': a.id, 'is_read': a.is_read, 'dismissed': a.dismissed,
                                   'status': a.status}})


@csrf_exempt
@require_POST
@require_farmer
def soil_profile_update(request, field_id):
    """Upsert SoilProfile for a field — FC/PWP/root_depth feed irrigation engine."""
    from .models import SoilProfile
    fl = get_owned_field(request.farmer, field_id)
    if fl is None:
        return JsonResponse({'error': 'قطعه زمین یافت نشد'}, status=404)
    data = json_body(request)
    if data is None:
        return JsonResponse({'error': 'JSON نامعتبر'}, status=400)
    obj, _ = SoilProfile.objects.get_or_create(field=fl)
    numeric = {'ph', 'organic_matter', 'field_capacity', 'wilting_point', 'root_depth_cm'}
    for k in numeric | {'notes'}:
        if k in data:
            v = data[k]
            setattr(obj, k, (float(v) if v not in ('', None) and k in numeric else (v or '')) if k in numeric else (v or ''))
    obj.save()
    return JsonResponse({'soil': {'ph': obj.ph, 'organic_matter': obj.organic_matter,
                                  'field_capacity': obj.field_capacity, 'wilting_point': obj.wilting_point,
                                  'root_depth_cm': obj.root_depth_cm, 'notes': obj.notes}})


@require_GET
@require_farmer
def soil_profile_get(request, field_id):
    from .models import SoilProfile
    fl = get_owned_field(request.farmer, field_id)
    if fl is None:
        return JsonResponse({'error': 'قطعه زمین یافت نشد'}, status=404)
    obj = SoilProfile.objects.filter(field=fl).first()
    if obj is None:
        return JsonResponse({'soil': None})
    return JsonResponse({'soil': {'ph': obj.ph, 'organic_matter': obj.organic_matter,
                                  'field_capacity': obj.field_capacity, 'wilting_point': obj.wilting_point,
                                  'root_depth_cm': obj.root_depth_cm, 'notes': obj.notes}})


@csrf_exempt
@require_POST
@require_farmer
def water_source_create(request, farm_id):
    """Add a WaterSource to a farm."""
    from .models import WaterSource
    farm = get_owned_farm(request.farmer, farm_id)
    if farm is None:
        return JsonResponse({'error': 'مزرعه یافت نشد'}, status=404)
    data = json_body(request)
    if data is None:
        return JsonResponse({'error': 'JSON نامعتبر'}, status=400)
    name = (data.get('name') or '').strip()
    if not name:
        return JsonResponse({'error': 'نام منبع آب لازم است'}, status=400)
    obj = WaterSource.objects.create(
        farm=farm, name=name, kind=data.get('kind', ''),
        capacity_m3=data.get('capacity_m3') or None, notes=data.get('notes', ''))
    return JsonResponse({'water_source': {'id': obj.id, 'name': obj.name, 'kind': obj.kind,
                                          'capacity_m3': obj.capacity_m3}}, status=201)


@require_GET
@require_farmer
def water_source_list(request, farm_id):
    from .models import WaterSource
    farm = get_owned_farm(request.farmer, farm_id)
    if farm is None:
        return JsonResponse({'error': 'مزرعه یافت نشد'}, status=404)
    items = [{'id': w.id, 'name': w.name, 'kind': w.kind,
              'capacity_m3': w.capacity_m3, 'notes': w.notes}
             for w in WaterSource.objects.filter(farm=farm)]
    return JsonResponse({'water_sources': items})


@csrf_exempt
@require_POST
@require_farmer
def agent_tool(request):
    """Controlled tool execution for the Farmer Agent (Phase 6).

    POST {tool, params, confirm?} — mutating tools return 409 + preview
    unless confirm=true.
    """
    from core.services.tools import AgentContext, ConfirmationRequired, PermissionDenied, ToolError, get_context, save_context
    from .services.tools import get_registry
    data = json_body(request)
    if data is None:
        return JsonResponse({'error': 'JSON نامعتبر'}, status=400)
    tool_name = (data.get('tool') or '').strip()
    params = data.get('params') or {}
    confirmed = bool(data.get('confirm'))
    # context bound to this farmer — never shared
    ctx = AgentContext(owner_key=request.farmer.api_key)
    ctx.farmer = request.farmer
    if data.get('field_id'):
        ctx.active_field_id = data['field_id']
    registry = get_registry()
    try:
        out = registry.run(tool_name, params, context=ctx, confirmed=confirmed)
    except ConfirmationRequired as e:
        return JsonResponse({'confirmation_required': True, 'tool': e.tool_name,
                             'preview': e.preview,
                             'message': 'این عملیات داده را تغییر می‌دهد — برای تأیید confirm=true بفرستید.'}, status=409)
    except PermissionDenied as e:
        return JsonResponse({'error': str(e)}, status=403)
    except ToolError as e:
        return JsonResponse({'error': str(e)}, status=400)
    return JsonResponse(out)


@require_GET
@require_farmer
def agent_tools_list(request):
    """List available agent tools."""
    from .services.tools import get_registry
    return JsonResponse({'tools': get_registry().list_tools()})


@csrf_exempt
@require_POST
@rate_limit(20, 60, 'farmer-login')
def farmer_login(request):
    """Session login — api_key (legacy) or login+password (account)."""
    data = json_body(request)
    if data is None:
        return JsonResponse({'error': 'JSON نامعتبر'}, status=400)
    key = (data.get('api_key') or data.get('key') or '').strip()
    if key:
        farmer = FarmerProfile.objects.filter(api_key=key).first()
        if farmer is None:
            return JsonResponse({'error': 'کلید نامعتبر'}, status=401)
    else:
        login = (data.get('login') or data.get('email') or data.get('phone') or '').strip()
        password = data.get('password') or ''
        farmer = FarmerProfile.objects.filter(login__iexact=login.lower() if '@' in login else login).first() if login else None
        if farmer is None or not farmer.password_hash or not farmer.is_active or not check_password(password, farmer.password_hash):
            return JsonResponse({'error': 'نام کاربری یا رمز عبور نامعتبر است'}, status=401)
        farmer.last_login = timezone.now()
        farmer.save(update_fields=['last_login'])
    request.session['farmer_id'] = farmer.id
    request.session.set_expiry(60 * 60 * 24 * 30)  # 30 days
    return JsonResponse({'ok': True, 'farmer': farmer_to_dict(farmer)})


@require_POST
def farmer_logout(request):
    request.session.pop('farmer_id', None)
    return JsonResponse({'ok': True})


@require_GET
def farmer_me(request):
    """Return current farmer (session or api_key)."""
    farmer = get_farmer(request)
    if farmer is None:
        return JsonResponse({'error': 'احراز هویت نشده'}, status=401)
    return JsonResponse({'farmer': farmer_to_dict(farmer),
                         'auth': 'session' if request.session.get('farmer_id') == farmer.id else 'api_key'})


def dashboard(request):
    from django.shortcuts import render
    return render(request, 'farmer/dashboard.html')
