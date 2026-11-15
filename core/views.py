import json
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponse
from django.utils import timezone
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from .services.nasa import fetch_power, search_collections, search_granules, download_nasa_file, inspect_downloaded_file, PARAMETER_INFO
from .faq_data import FAQ
from .services.fao import CROPS as FAO_CROPS, fetch_crop, fetch_world
from .services.advice import get_advice
from .services.geocode import search_places
from .services.throttle import rate_limit
from .services.climate import get_climate_indicators
from .services.agent import answer_question
from .services.report import build_climate_pdf
from .services.auth import require_account, get_account

def dashboard(request):
    if get_account(request) is None:
        return render(request, 'core/login.html')
    return render(request, 'core/dashboard.html')


def landing(request): return render(request, 'core/landing.html')

@require_GET
def health(request):
    deep = request.GET.get('deep') == '1'
    checks = {'database': 'not_checked', 'cache': 'not_checked'}
    if deep:
        checks = {'database': False, 'cache': False}
        try:
            from django.db import connection
            with connection.cursor() as cur:
                cur.execute('SELECT 1')
            checks['database'] = True
        except Exception:
            pass
        try:
            from django.core.cache import cache
            cache.set('health:ping', '1', timeout=5)
            checks['cache'] = cache.get('health:ping') == '1'
        except Exception:
            pass
        status = 'ok' if all(checks.values()) else 'degraded'
    else:
        status = 'ok'
    return JsonResponse({'status': status, 'checks': checks,
                         'application': 'Earth Intelligence Platform',
                         'power': 'configured', 'cmr': 'configured', 'fao': 'configured',
                         'earthdata_auth': 'configured' if settings.NASA_EARTHDATA_TOKEN else 'not_configured'})


@require_GET
@rate_limit(30, 60, 'metrics')
def metrics(request):
    from .services.monitoring import snapshot
    return JsonResponse(snapshot())

@require_GET
@require_account
def power_parameters(request):
    return JsonResponse({'parameters':[{'code':k,'name_en':v[0],'name_fa':v[1],'unit':v[2]} for k,v in PARAMETER_INFO.items()]})

@require_GET
@rate_limit(30, 60, 'power')
@require_account
def power(request):
    try:
        params=request.GET.getlist('parameter') or None
        data=fetch_power(request.GET.get('lat',''),request.GET.get('lon',''),request.GET.get('start',''),request.GET.get('end',''),params,request.GET.get('community','AG'),request.GET.get('temporal','daily'))
        return JsonResponse(data)
    except (ValueError, TypeError) as e: return JsonResponse({'error':str(e)},status=400)
    except Exception as e: return JsonResponse({'error':f'NASA POWER request failed: {e}'},status=502)

@require_GET
@rate_limit(30, 60, 'catalog')
@require_account
def catalog(request):
    try:
        data=search_collections(request.GET.get('q',''),request.GET.get('provider',''),request.GET.get('page',1),request.GET.get('page_size',12),request.GET.get('start',''),request.GET.get('end',''),request.GET.get('point',''),request.GET.get('cursor',''))
        return JsonResponse(data)
    except (ValueError, TypeError) as e: return JsonResponse({'error':str(e)},status=400)
    except Exception as e: return JsonResponse({'error':f'NASA CMR search failed: {e}'},status=502)

@require_GET
@rate_limit(30, 60, 'granules')
@require_account
def granules(request):
    try:
        data=search_granules(request.GET.get('concept_id',''),request.GET.get('start',''),request.GET.get('end',''),request.GET.get('bbox',''),request.GET.get('page',1),request.GET.get('page_size',10),request.GET.get('cursor',''))
        return JsonResponse(data)
    except (ValueError, TypeError) as e: return JsonResponse({'error':str(e)},status=400)
    except Exception as e: return JsonResponse({'error':f'NASA granule search failed: {e}'},status=502)

@csrf_exempt
@require_POST
@rate_limit(10, 60, 'download')
@require_account
def download_granule(request):
    try:
        payload=json.loads(request.body or '{}'); result=download_nasa_file(payload.get('url',''))
        return JsonResponse({'ok':True,**result})
    except (ValueError, TypeError, json.JSONDecodeError) as e: return JsonResponse({'error':str(e)},status=400)
    except Exception as e: return JsonResponse({'error':f'Download failed: {e}'},status=502)

@require_GET
@require_account
def faq(request):
    lang=request.GET.get('lang','fa'); q=request.GET.get('q','').strip().casefold(); category=request.GET.get('category','')
    results=[]
    for item in FAQ:
        text=' '.join([item['q_fa'],item['a_fa'],item['q_en'],item['a_en'],item['category']]).casefold()
        if q and q not in text: continue
        if category and item['category']!=category: continue
        results.append({'category':item['category'],'question':item['q_fa' if lang=='fa' else 'q_en'],'answer':item['a_fa' if lang=='fa' else 'a_en']})
    return JsonResponse({'count':len(results),'items':results,'categories':sorted(set(x['category'] for x in FAQ))})

@require_GET
@require_account
def inspect_file(request):
    try: return JsonResponse(inspect_downloaded_file(request.GET.get('file','')))
    except (ValueError, TypeError) as e: return JsonResponse({'error':str(e)},status=400)
    except ImportError as e: return JsonResponse({'error':f'Optional data reader is not installed: {e}'},status=501)
    except Exception as e: return JsonResponse({'error':f'File inspection failed: {e}'},status=422)


@require_GET
@require_account
def fao_crops(request):
    return JsonResponse({'source':'FAOSTAT','domain':'QCL','area':'Iran','items':FAO_CROPS})

@require_GET
@rate_limit(10, 60, 'advice')
@require_account
def advice(request):
    try:
        return JsonResponse(get_advice(request.GET.get('lat',''), request.GET.get('lon',''), request.GET.get('crop','wheat')))
    except ValueError as e:
        return JsonResponse({'error':str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'error':f'Advice generation failed: {e}'}, status=502)

@require_GET
@rate_limit(20, 60, 'geocode')
@require_account
def geocode(request):
    try:
        items = search_places(request.GET.get('q', ''))
        return JsonResponse({'count': len(items), 'items': items})
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'Place search failed: {e}'}, status=502)

@require_GET
@rate_limit(10, 60, 'climate')
@require_account
def climate(request):
    try:
        return JsonResponse(get_climate_indicators(
            request.GET.get('lat', ''), request.GET.get('lon', ''),
            request.GET.get('start', ''), request.GET.get('end', '')))
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'Climate analysis failed: {e}'}, status=502)

@require_GET
@rate_limit(30, 60, 'fao')
@require_account
def fao_crop(request, crop_key):
    try:
        force = request.GET.get('refresh') == '1'
        return JsonResponse(fetch_crop(crop_key, force=force))
    except ValueError as e:
        return JsonResponse({'error':str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'error':str(e)}, status=502)

@require_GET
@rate_limit(5, 60, 'report')
@require_account
def climate_report(request):
    from django.http import HttpResponse
    try:
        data = get_climate_indicators(
            request.GET.get('lat', ''), request.GET.get('lon', ''),
            request.GET.get('start', ''), request.GET.get('end', ''))
        pdf = build_climate_pdf(data)
        return HttpResponse(pdf, content_type='application/pdf',
                            headers={'Content-Disposition': 'attachment; filename="climate-report.pdf"'})
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'Report generation failed: {e}'}, status=502)

@require_GET
@rate_limit(10, 60, 'agent')
@require_account
def agent(request):
    try:
        lat = request.GET.get('lat') or None
        lon = request.GET.get('lon') or None
        if lat is not None:
            lat = float(lat)
        if lon is not None:
            lon = float(lon)
        return JsonResponse(answer_question(
            request.GET.get('q', ''), lat=lat, lon=lon,
            crop=request.GET.get('crop') or None))
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'Agent failed: {e}'}, status=502)

@require_GET
@rate_limit(10, 60, 'fao-world')
@require_account
def fao_world(request, crop_key):
    try:
        element = request.GET.get('element', 'production')
        top = min(int(request.GET.get('top', 10)), 25)
        return JsonResponse(fetch_world(crop_key, element=element, top=top))
    except ValueError as e:
        return JsonResponse({'error':str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'error':str(e)}, status=502)




# ---------- Phase 5 — Scientific Workspace ----------

def json_body(request):
    try:
        return json.loads(request.body.decode('utf-8')) if request.body else {}
    except Exception:
        return None


def _owner_key(request):
    account = getattr(request, 'account', None)
    if account is not None:
        return account.api_key
    return request.GET.get('owner') or request.META.get('HTTP_X_OWNER', 'anonymous')[:120]


def _analysis_dict(a):
    return {'id': a.id, 'title': a.title, 'analysis_type': a.analysis_type,
            'geo': a.geo, 'time_range': a.time_range, 'data_source': a.data_source,
            'parameters': a.parameters, 'viz_settings': a.viz_settings,
            'dataset_version': a.dataset_version, 'result_metadata': a.result_metadata,
            'created_at': a.created_at.isoformat(), 'updated_at': a.updated_at.isoformat()}


@csrf_exempt
@require_POST
@require_account
def analysis_save(request):
    """Save an analysis configuration for later reproduction."""
    from core.models import SavedAnalysis
    data = json_body(request)
    if data is None:
        return JsonResponse({'error': 'JSON نامعتبر'}, status=400)
    a = SavedAnalysis.objects.create(
        owner_key=_owner_key(request),
        title=(data.get('title') or '')[:200],
        analysis_type=data.get('analysis_type', 'custom')[:40],
        geo=data.get('geo') or {}, time_range=data.get('time_range') or {},
        data_source=(data.get('data_source') or '')[:80],
        parameters=data.get('parameters') or {},
        viz_settings=data.get('viz_settings') or {},
        dataset_version=(data.get('dataset_version') or '')[:120],
        result_metadata=data.get('result_metadata') or {})
    return JsonResponse({'analysis': _analysis_dict(a)}, status=201)


@require_GET
@require_account
def analysis_list(request):
    from core.models import SavedAnalysis
    qs = SavedAnalysis.objects.filter(owner_key=_owner_key(request))
    if request.GET.get('type'):
        qs = qs.filter(analysis_type=request.GET['type'])
    items = [_analysis_dict(a) for a in qs[:100]]
    return JsonResponse({'analyses': items, 'count': len(items)})


@require_GET
@require_account
def analysis_detail(request, analysis_id):
    from core.models import SavedAnalysis
    try:
        a = SavedAnalysis.objects.get(id=analysis_id, owner_key=_owner_key(request))
    except SavedAnalysis.DoesNotExist:
        return JsonResponse({'error': 'تحلیل یافت نشد'}, status=404)
    return JsonResponse({'analysis': _analysis_dict(a)})


@csrf_exempt
@require_POST
@require_account
def analysis_delete(request, analysis_id):
    from core.models import SavedAnalysis
    n, _ = SavedAnalysis.objects.filter(id=analysis_id, owner_key=_owner_key(request)).delete()
    if not n:
        return JsonResponse({'error': 'تحلیل یافت نشد'}, status=404)
    return JsonResponse({'deleted': True})


@require_GET
@require_account
def analysis_reproduce(request, analysis_id):
    """Re-run a saved analysis with its stored parameters."""
    from core.models import SavedAnalysis
    try:
        a = SavedAnalysis.objects.get(id=analysis_id, owner_key=_owner_key(request))
    except SavedAnalysis.DoesNotExist:
        return JsonResponse({'error': 'تحلیل یافت نشد'}, status=404)
    p = a.parameters or {}
    result = {'analysis_id': a.id, 'analysis_type': a.analysis_type,
              'reproduced_at': timezone.now().isoformat(), 'parameters_used': p}
    try:
        if a.analysis_type == 'power' or 'lat' in p:
            from core.services.nasa import fetch_power
            result['data'] = fetch_power(
                p.get('lat'), p.get('lon'), p.get('start'), p.get('end'),
                parameters=p.get('parameters'))
        elif a.analysis_type == 'timeseries':
            result['data'] = _run_timeseries(p)
        elif a.analysis_type == 'catalog':
            from core.services.nasa import search_collections
            result['data'] = search_collections(
                keyword=p.get('q', ''), provider=p.get('provider', ''),
                page=p.get('page', 1), page_size=p.get('page_size', 12),
                temporal_start=p.get('start', ''), temporal_end=p.get('end', ''),
                point=p.get('point'))
        else:
            result['note'] = 'custom type — parameters returned for manual replay'
    except Exception as e:
        result['error'] = str(e)
        return JsonResponse(result, status=502)
    a.result_metadata = {'last_reproduced': result['reproduced_at'],
                         'last_status': 'ok' if 'error' not in result else 'error'}
    a.save(update_fields=['result_metadata', 'updated_at'])
    return JsonResponse(result)


def _run_timeseries(p):
    """Time series for climate params — POWER daily data + optional baseline compare."""
    from core.services.nasa import fetch_power
    lat, lon = p.get('lat'), p.get('lon')
    start, end = p.get('start'), p.get('end')
    params = p.get('parameters') or ['T2M', 'PRECTOT', 'ALLSKY_SFC_SW_DWN', 'WS10M']
    if not all([lat is not None, lon is not None, start, end]):
        raise ValueError('lat/lon/start/end required')
    data = fetch_power(lat, lon, start, end, parameters=params)
    series = {}
    props = (data.get('properties') or {}).get('parameter') or {}
    for pname, dates in props.items():
        series[pname] = [{'date': d, 'value': v} for d, v in sorted(dates.items())]
    out = {'lat': lat, 'lon': lon, 'start': start, 'end': end,
           'parameters': params, 'series': series,
           'aggregation': p.get('aggregation', 'daily'),
           'baseline': p.get('baseline'), 'comparison': p.get('comparison')}
    baseline = p.get('baseline') or {}
    if baseline.get('start') and baseline.get('end'):
        bdata = fetch_power(lat, lon, baseline['start'], baseline['end'], parameters=params)
        bprops = (bdata.get('properties') or {}).get('parameter') or {}
        def _monthly(dates):
            agg = {}
            for d, v in dates.items():
                m = d[:7]
                agg.setdefault(m, []).append(v)
            return {m: sum(vs) / len(vs) for m, vs in agg.items()}
        out['baseline_series'] = {pn: _monthly(dv) for pn, dv in bprops.items()}
        out['comparison'] = 'vs_baseline_monthly_mean'
    return out


@require_GET
@require_account
def timeseries(request):
    """GET /api/timeseries/?lat&lon&start&end&parameters=T2M,PRECTOT&aggregation=daily&baseline_start&baseline_end"""
    p = {
        'lat': request.GET.get('lat'), 'lon': request.GET.get('lon'),
        'start': request.GET.get('start'), 'end': request.GET.get('end'),
        'parameters': [x for x in (request.GET.get('parameters') or 'T2M,PRECTOT').split(',') if x],
        'aggregation': request.GET.get('aggregation', 'daily'),
        'baseline': {'start': request.GET.get('baseline_start'), 'end': request.GET.get('baseline_end')},
        'comparison': request.GET.get('comparison', 'vs_baseline'),
    }
    try:
        return JsonResponse(_run_timeseries(p))
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=502)


@require_GET
@require_account
def collection_detail(request, concept_id):
    """CMR collection metadata + granule count + download info."""
    from core.services.nasa import fetch_json, CMR_BASE
    try:
        data = fetch_json(f'{CMR_BASE}/collections/{concept_id}',
                          headers={'Accept': 'application/vnd.nasa.cmr.umm_json'},
                          timeout=30, source='NASA CMR')
        umm = data.get('umm', data)
        return JsonResponse({
            'concept_id': concept_id,
            'title': umm.get('ShortName') or umm.get('EntryTitle', ''),
            'abstract': umm.get('Abstract', ''),
            'provider': umm.get('Provider', ''),
            'temporal': umm.get('TemporalExtents', []),
            'spatial': umm.get('SpatialExtents', []),
            'granule_count': umm.get('GranuleCount'),
            'download': {'cmr_url': f'https://cmr.earthdata.nasa.gov/search/concepts/{concept_id}',
                         'api_url': f'{CMR_BASE}/granules?concept_id={concept_id}'}})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=502)


@require_GET
@require_account
def export_analysis(request, analysis_id):
    """Export saved analysis as CSV or PDF with full metadata."""
    from core.models import SavedAnalysis
    fmt = request.GET.get('format', 'csv')
    try:
        a = SavedAnalysis.objects.get(id=analysis_id, owner_key=_owner_key(request))
    except SavedAnalysis.DoesNotExist:
        return JsonResponse({'error': 'تحلیل یافت نشد'}, status=404)
    meta = {
        'Data Source': a.data_source or 'NASA POWER / CMR',
        'Dataset': a.dataset_version or 'live',
        'Analysis Type': a.analysis_type,
        'Parameters': json.dumps(a.parameters, ensure_ascii=False),
        'Geo': json.dumps(a.geo, ensure_ascii=False),
        'Time Range': json.dumps(a.time_range, ensure_ascii=False),
        'Generated': timezone.now().isoformat(),
        'Methodology': 'FAO-56 / NASA POWER / CMR — see docs',
        'Limitations': 'Grid-based estimates; not field measurements.',
    }
    import io
    if fmt == 'csv':
        import csv
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(['Field', 'Value'])
        for k, v in meta.items():
            w.writerow([k, v])
        resp = HttpResponse(buf.getvalue(), content_type='text/csv')
        resp['Content-Disposition'] = f'attachment; filename="analysis_{a.id}.csv"'
        return resp
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas as pdfcanvas
    buf = io.BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=A4)
    y = 800
    c.setFont('Helvetica-Bold', 16)
    c.drawString(50, y, f'Scientific Analysis Report — #{a.id}')
    y -= 30
    c.setFont('Helvetica', 10)
    for k, v in meta.items():
        c.drawString(50, y, f'{k}: {str(v)[:90]}')
        y -= 16
        if y < 60:
            c.showPage(); y = 800; c.setFont('Helvetica', 10)
    c.save()
    buf.seek(0)
    resp = HttpResponse(buf.getvalue(), content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="analysis_{a.id}.pdf"'
    return resp


@require_GET
@require_account
def data_quality(request):
    """DataQualityReport — snapshot stats per dataset (Phase 1)."""
    from django.db.models import Count, Q, Max
    from core.models import DataSnapshot, DataIngestionLog
    from django.utils import timezone
    from datetime import timedelta
    snaps = DataSnapshot.objects.values('dataset__source__key', 'dataset__key').annotate(
        total=Count('id'),
        valid=Count('id', filter=Q(quality_status='valid')),
        partial=Count('id', filter=Q(quality_status='partial')),
        stale=Count('id', filter=Q(quality_status='stale')),
        invalid=Count('id', filter=Q(quality_status='invalid')),
        latest=Max('retrieved_at'),
    )
    day_ago = timezone.now() - timedelta(days=1)
    recent_logs = DataIngestionLog.objects.filter(created_at__gte=day_ago).values(
        'source__key', 'status').annotate(n=Count('id'))
    logs_summary = {}
    for row in recent_logs:
        logs_summary.setdefault(row['source__key'], {})[row['status']] = row['n']
    return JsonResponse({
        'generated_at': timezone.now().isoformat(),
        'snapshots': list(snaps),
        'ingestion_last_24h': logs_summary,
        'limitations': ['Counts reflect persisted snapshots/logs only — cached responses may not appear.'],
    })
