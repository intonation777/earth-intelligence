import os, re, uuid
from datetime import datetime, timezone
from urllib.parse import urlparse
import requests
from django.conf import settings
from .http import fetch_json, DataSourceError


def _now_iso():
    return datetime.now(timezone.utc).isoformat()

POWER_BASE = 'https://power.larc.nasa.gov/api/temporal'
CMR_BASE = 'https://cmr.earthdata.nasa.gov/search'
DEFAULT_PARAMETERS = ['T2M','T2M_MAX','T2M_MIN','PRECTOTCORR','RH2M','WS10M','ALLSKY_SFC_SW_DWN','T2MDEW','PS','EVPTRNS']
PARAMETER_INFO = {
 'T2M':('Temperature at 2 Meters','دمای هوا در ارتفاع ۲ متر','°C'),
 'T2M_MAX':('Maximum Temperature at 2 Meters','بیشینه دمای هوا در ارتفاع ۲ متر','°C'),
 'T2M_MIN':('Minimum Temperature at 2 Meters','کمینه دمای هوا در ارتفاع ۲ متر','°C'),
 'PRECTOTCORR':('Corrected Precipitation','بارش تصحیح‌شده','mm/day'),
 'RH2M':('Relative Humidity at 2 Meters','رطوبت نسبی در ارتفاع ۲ متر','%'),
 'WS10M':('Wind Speed at 10 Meters','سرعت باد در ارتفاع ۱۰ متر','m/s'),
 'ALLSKY_SFC_SW_DWN':('All Sky Surface Shortwave Downward Irradiance','تابش موج‌کوتاه فرودی سطح در همه شرایط آسمان','kWh/m²/day'),
 'T2MDEW':('Dew/Frost Point at 2 Meters','دمای نقطه شبنم/یخبندان','°C'),
 'PS':('Surface Pressure','فشار سطحی','kPa'),
 'EVPTRNS':('Evapotranspiration','تبخیر و تعرق','mm/day'),
}

def _date(value, name):
    try: return datetime.strptime(value, '%Y%m%d').strftime('%Y%m%d')
    except (ValueError, TypeError): raise ValueError(f'{name} must use YYYYMMDD format')

def fetch_power(lat, lon, start, end, parameters=None, community='AG', temporal='daily'):
    lat, lon = float(lat), float(lon)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180): raise ValueError('Latitude/longitude out of range')
    temporal = temporal.lower()
    if temporal not in ('hourly','daily','monthly','climatology'): raise ValueError('Temporal level must be hourly, daily, monthly or climatology')
    if temporal == 'climatology':
        start, end = '', ''
    else:
        start, end = _date(start,'start'), _date(end,'end')
        if start > end: raise ValueError('Start date must be before end date')
        span=(datetime.strptime(end,'%Y%m%d')-datetime.strptime(start,'%Y%m%d')).days
        limits={'hourly':31,'daily':7300,'monthly':18250}
        if span > limits[temporal]: raise ValueError(f'{temporal} request range exceeds {limits[temporal]} days; split the request into smaller windows')
    params = parameters or DEFAULT_PARAMETERS
    params = list(dict.fromkeys([p.strip().upper() for p in params if re.fullmatch(r'[A-Z0-9_]{2,40}', p.strip().upper())]))
    if not params or len(params) > 20: raise ValueError('Select between 1 and 20 valid parameters')
    if community not in ('AG','RE','SB','HY'): raise ValueError('Community must be AG, RE, SB or HY')
    community_note = None
    if temporal == 'monthly' and community != 'AG':
        community_note = f'Monthly POWER data is only published for the AG community; requested {community} was switched to AG.'
        community = 'AG'
    url = f'{POWER_BASE}/{temporal}/point'
    query={'parameters':','.join(params),'community':community,'longitude':lon,'latitude':lat,'format':'JSON'}
    if temporal != 'climatology':
        if temporal == 'monthly':
            query.update({'start':start[:4],'end':end[:4],'time-standard':'UTC'})
        else:
            query.update({'start':start,'end':end,'time-standard':'UTC'})
    try:
        payload = fetch_json(url, params=query, timeout=settings.NASA_POWER_TIMEOUT,
                             max_retries=2, backoff=1.5, source='NASA POWER')
    except DataSourceError as exc:
        raise ValueError(str(exc)) from exc
    source_url = requests.Request('GET', url, params=query).prepare().url
    properties = payload.get('properties', {})
    parameter_data = properties.get('parameter', {})
    if not parameter_data: raise ValueError('NASA POWER returned no parameter data for this request')
    dates = sorted({d for values in parameter_data.values() for d in values.keys()})
    series = []
    for code, values in parameter_data.items():
        en, fa, unit = PARAMETER_INFO.get(code, (code, code, 'NASA-defined unit'))
        points = [{'date': d, 'value': (None if v == -999 else v)} for d,v in sorted(values.items())]
        series.append({'code':code,'name_en':en,'name_fa':fa,'unit':unit,'points':points})
    result = {'source':'NASA POWER','temporal':temporal,'community':community,'community_note':community_note,'source_url':source_url,'fetched_at':_now_iso(),'geometry':payload.get('geometry',{}),'header':payload.get('header',{}),'parameters':series,'dates':dates,'metadata':properties.get('parameter',{}),'quality_note':'NASA POWER parameter values and units should be interpreted using the returned parameter metadata. Missing sentinel values (-999) are represented as null.',
        'provenance': _power_provenance(lat, lon, temporal, community, source_url)}
    try:
        from .provenance_store import record_snapshot
        record_snapshot('nasa_power', f'power_{temporal}_point',
                        f'{lat},{lon},{start}-{end}', result['provenance'],
                        payload_ref=source_url,
                        metadata={'lat': lat, 'lon': lon, 'start': start, 'end': end,
                                  'parameters': params, 'community': community})
    except Exception:
        pass
    return result


def _power_provenance(lat, lon, temporal, community, source_url):
    """Data Contract envelope for POWER responses (Phase 1)."""
    from .data_contract import DataContract, validate_contract, quality_from_issues
    c = DataContract.now(
        source='NASA POWER', dataset_id=f'power_{temporal}_point',
        kind='numeric', parameter=','.join(DEFAULT_PARAMETERS[:3]),
        original_unit='mixed (per-parameter)', normalized_unit='SI-ish (°C, mm, kWh/m²/day)',
        lat=lat, lon=lon, temporal_resolution=temporal,
        spatial_resolution='point (~0.5° grid)',
        limitations=['Grid-based meteorological estimate — not a direct field measurement.'],
        metadata={'community': community, 'source_url': source_url})
    issues = validate_contract(c)
    return {**c.to_dict(), 'quality_issues': issues, 'quality_status': quality_from_issues(issues)}

def search_collections(keyword='', provider='', page=1, page_size=12, temporal_start='', temporal_end='', point=None, search_after=''):
    # CMR Search-After is the supported cursor mechanism for deep pagination.
    page_size=max(1,min(int(page_size),2000))
    params={'page_size':page_size,'sort_key':'-score','has_granules':'true'}
    if keyword:
        kw = keyword.strip()
        # short_name only for exact collection short names (contain underscore);
        # generic terms like 'MODIS'/'landsat' must use keyword search
        if '_' in kw and re.fullmatch(r'[A-Za-z0-9_]{4,80}', kw):
            params['short_name'] = kw
        else:
            params['keyword'] = kw[:180]
    if provider: params['provider']=provider[:80]
    if temporal_start or temporal_end:
        params['temporal']=f"{temporal_start or ''},{temporal_end or ''}"
    if point: params['point']=point
    headers={'Accept':'application/vnd.nasa.cmr.umm_results+json'}
    if search_after:
        if len(search_after)>4096 or not re.fullmatch(r'[A-Za-z0-9._~:+/=-]+',search_after):
            raise ValueError('Invalid CMR Search-After cursor')
        headers['CMR-Search-After']=search_after
    try:
        data, resp_headers = fetch_json(f'{CMR_BASE}/collections.umm_json', params=params, headers=headers,
                                        timeout=settings.NASA_CMR_TIMEOUT, max_retries=2, backoff=1.5,
                                        return_headers=True, source='NASA CMR')
    except DataSourceError as exc:
        raise ValueError(str(exc)) from exc
    items=[]
    for entry in data.get('items',[]):
        meta=entry.get('umm',{}); temporal=meta.get('TemporalExtents',[])
        ranges=[]
        for t in temporal:
            for r in t.get('RangeDateTimes',[]): ranges.append({'start':r.get('BeginningDateTime'),'end':r.get('EndingDateTime')})
        platforms=[p.get('ShortName') or p.get('LongName') or '' for p in meta.get('Platforms',[])]
        concept=entry.get('meta',{}).get('concept-id')
        short=meta.get('ShortName','')
        items.append({'concept_id':concept,'title':meta.get('EntryTitle'),'short_name':short,'version':meta.get('Version'),'provider':entry.get('meta',{}).get('provider-id'),'abstract':meta.get('Abstract',''),'platforms':platforms,'temporal':ranges,'collection_url':f"https://search.earthdata.nasa.gov/search?q={short}",'metadata_url':f"https://cmr.earthdata.nasa.gov/search/concepts/{concept}"})
    result = {'source':'NASA Earthdata CMR','hits':int(resp_headers.get('CMR-Hits',len(items))),'page':max(1,int(page)),'page_size':page_size,'items':items,'next_cursor':resp_headers.get('CMR-Search-After'),'fetched_at':_now_iso()}
    try:
        from .data_contract import DataContract, validate_contract, quality_from_issues
        from .provenance_store import record_snapshot
        c = DataContract.now(source='NASA CMR', dataset_id='cmr_collections',
                             kind='metadata', parameter=keyword or '',
                             temporal_resolution='variable', spatial_resolution='global',
                             limitations=['Catalog metadata — not data values.'])
        issues = validate_contract(c)
        result['provenance'] = {**c.to_dict(), 'quality_issues': issues,
                                'quality_status': quality_from_issues(issues)}
        record_snapshot('nasa_cmr', 'cmr_collections', f'p{page}:{keyword}',
                        result['provenance'], payload_ref=CMR_BASE)
    except Exception:
        pass
    return result

def search_granules(concept_id, start='', end='', bbox='', page=1, page_size=10, search_after=''):
    if not re.fullmatch(r'C[0-9]+-[A-Z0-9_-]+', concept_id or ''): raise ValueError('Invalid CMR collection concept ID')
    params={'collection_concept_id':concept_id,'page_size':max(1,min(int(page_size),2000)),'sort_key':'-start_date','downloadable':'true'}
    headers={'Accept':'application/vnd.nasa.cmr.umm_results+json'}
    if search_after:
        if len(search_after)>4096 or not re.fullmatch(r'[A-Za-z0-9._~:+/=-]+',search_after): raise ValueError('Invalid CMR Search-After cursor')
        headers['CMR-Search-After']=search_after
    if start or end: params['temporal']=(start or '')+','+(end or '')
    if bbox:
        vals=[float(x) for x in bbox.split(',')]
        if len(vals)!=4 or not(-180<=vals[0]<=180 and -180<=vals[2]<=180 and -90<=vals[1]<=90 and -90<=vals[3]<=90): raise ValueError('bbox must be west,south,east,north')
        params['bounding_box']=bbox
    try:
        data, resp_headers = fetch_json(f'{CMR_BASE}/granules.umm_json', params=params, headers=headers,
                                        timeout=settings.NASA_CMR_TIMEOUT, max_retries=2, backoff=1.5,
                                        return_headers=True, source='NASA CMR')
    except DataSourceError as exc:
        raise ValueError(str(exc)) from exc
    items=[]
    for entry in data.get('items',[]):
        meta=entry.get('umm',{}); urls=[]
        for rel in meta.get('RelatedUrls',[]):
            if rel.get('Type') in ('GET DATA','GET DATA VIA DIRECT ACCESS','EXTENDED METADATA') and rel.get('URL'): urls.append({'url':rel['URL'],'type':rel.get('Type'),'description':rel.get('Description','')})
        items.append({'concept_id':entry.get('meta',{}).get('concept-id'),'producer_id':meta.get('ProducerGranuleId'),'title':meta.get('GranuleUR'),'start':meta.get('TemporalExtent',{}).get('RangeDateTime',{}).get('BeginningDateTime'),'end':meta.get('TemporalExtent',{}).get('RangeDateTime',{}).get('EndingDateTime'),'size_mb':meta.get('DataGranule',{}).get('ArchiveAndDistributionInformation',[{}])[0].get('SizeInBytes'),'links':urls})
    result = {'source':'NASA Earthdata CMR Granule Search','hits':int(resp_headers.get('CMR-Hits',len(items))),'items':items,'next_cursor':resp_headers.get('CMR-Search-After'),'fetched_at':_now_iso()}
    try:
        from .data_contract import DataContract, validate_contract, quality_from_issues
        from .provenance_store import record_snapshot
        c = DataContract.now(source='NASA CMR', dataset_id='cmr_granules',
                             kind='metadata', parameter=concept_id,
                             temporal_resolution='variable', spatial_resolution='granule',
                             limitations=['Granule metadata — files require Earthdata auth to download.'])
        issues = validate_contract(c)
        result['provenance'] = {**c.to_dict(), 'quality_issues': issues,
                                'quality_status': quality_from_issues(issues)}
        record_snapshot('nasa_cmr', 'cmr_granules', f'{concept_id}:p{page}',
                        result['provenance'], payload_ref=CMR_BASE)
    except Exception:
        pass
    return result

def download_nasa_file(url):
    parsed=urlparse(url)
    allowed=('lpdaac.usgs.gov','nsidc.org','podaac.jpl.nasa.gov','data.nasa.gov','earthdata.nasa.gov','nasa.gov','s3.amazonaws.com','s3.us-west-2.amazonaws.com')
    if parsed.scheme!='https' or not any(parsed.hostname==d or (parsed.hostname or '').endswith('.'+d) for d in allowed):
        raise ValueError('Only HTTPS downloads from approved NASA/DAAC domains are allowed')
    headers={}
    if settings.NASA_EARTHDATA_TOKEN: headers['Authorization']=f'Bearer {settings.NASA_EARTHDATA_TOKEN}'
    r=requests.get(url,headers=headers,stream=True,timeout=settings.NASA_CMR_TIMEOUT,allow_redirects=True)
    r.raise_for_status()
    final_host=urlparse(r.url).hostname or ''
    if not any(final_host==d or final_host.endswith('.'+d) for d in allowed): raise ValueError('Redirect to a non-approved host blocked')
    max_bytes=settings.NASA_DOWNLOAD_MAX_MB*1024*1024
    length=int(r.headers.get('Content-Length','0') or 0)
    if length and length>max_bytes: raise ValueError(f'File exceeds configured limit ({settings.NASA_DOWNLOAD_MAX_MB} MB)')
    name=os.path.basename(urlparse(r.url).path) or f'nasa-{uuid.uuid4().hex}.bin'
    name=re.sub(r'[^A-Za-z0-9._-]','_',name)[:120]
    folder=settings.MEDIA_ROOT/'nasa_downloads'; folder.mkdir(parents=True,exist_ok=True)
    path=folder/f'{uuid.uuid4().hex}_{name}'; total=0
    with open(path,'wb') as out:
        for chunk in r.iter_content(1024*1024):
            if not chunk: continue
            total+=len(chunk)
            if total>max_bytes:
                out.close(); path.unlink(missing_ok=True); raise ValueError('Download exceeded configured size limit')
            out.write(chunk)
    return {'name':name,'path':str(path),'bytes':total,'media_url':f'{settings.MEDIA_URL}nasa_downloads/{path.name}'}

def inspect_downloaded_file(filename):
    from pathlib import Path
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,180}', filename or ''): raise ValueError('Invalid file name')
    folder=(settings.MEDIA_ROOT/'nasa_downloads').resolve(); path=(folder/filename).resolve()
    if path.parent!=folder or not path.is_file(): raise ValueError('Downloaded file not found')
    suffix=path.suffix.lower(); result={'file':path.name,'bytes':path.stat().st_size,'format':suffix.lstrip('.'),'inspection':'metadata'}
    if suffix in ('.csv','.txt'):
        import pandas as pd
        frame=pd.read_csv(path,nrows=10000)
        result.update({'rows_sampled':len(frame),'columns':[{'name':str(c),'dtype':str(frame[c].dtype),'missing':int(frame[c].isna().sum()),'min':(float(frame[c].min()) if pd.api.types.is_numeric_dtype(frame[c]) and frame[c].notna().any() else None),'max':(float(frame[c].max()) if pd.api.types.is_numeric_dtype(frame[c]) and frame[c].notna().any() else None)} for c in frame.columns]})
    elif suffix in ('.json','.geojson'):
        import json as _json
        with open(path,encoding='utf-8') as f: obj=_json.load(f)
        result.update({'root_type':type(obj).__name__,'top_level_keys':list(obj.keys())[:100] if isinstance(obj,dict) else [],'feature_count':len(obj.get('features',[])) if isinstance(obj,dict) and obj.get('type')=='FeatureCollection' else None})
    elif suffix in ('.h5','.hdf5'):
        import h5py
        entries=[]
        with h5py.File(path,'r') as f:
            def visit(name,obj):
                if isinstance(obj,h5py.Dataset) and len(entries)<250:
                    entry={'path':name,'shape':list(obj.shape),'dtype':str(obj.dtype),'attrs':{str(k):str(v)[:200] for k,v in list(obj.attrs.items())[:12]}}
                    if obj.shape and obj.dtype.kind in 'iuf' and len(entries)<60:
                        import numpy as np
                        sample=obj[tuple(slice(0,min(int(n),100)) for n in obj.shape)]
                        fill=obj.attrs.get('_FillValue',obj.attrs.get('missing_value'))
                        scale=float(obj.attrs.get('scale_factor',1)); offset=float(obj.attrs.get('add_offset',0))
                        arr=np.asarray(sample,dtype='float64')
                        mask=np.isfinite(arr)
                        if fill is not None: mask &= arr != float(np.asarray(fill).reshape(-1)[0])
                        valid=arr[mask]*scale+offset
                        entry['preview_stats']={'sampled_valid':int(valid.size),'min':float(valid.min()) if valid.size else None,'max':float(valid.max()) if valid.size else None,'mean':float(valid.mean()) if valid.size else None,'scale_factor':scale,'add_offset':offset,'fill_value':str(fill)}
                    entries.append(entry)
            f.visititems(visit)
        result.update({'datasets':entries,'dataset_count':len(entries),'note':'Metadata and dataset shapes only; apply product-specific scale factors, fill values and quality flags before scientific interpretation.'})
    elif suffix in ('.nc','.nc4','.netcdf'):
        import xarray as xr
        with xr.open_dataset(path,decode_cf=True) as ds:
            variables=[]
            for name,var in list(ds.data_vars.items())[:250]:
                item={'name':name,'dimensions':list(var.dims),'shape':list(var.shape),'dtype':str(var.dtype),'units':str(var.attrs.get('units','')),'long_name':str(var.attrs.get('long_name','')),'scale_factor':var.encoding.get('scale_factor'),'add_offset':var.encoding.get('add_offset'),'_FillValue':str(var.encoding.get('_FillValue',''))}
                if var.dtype.kind in 'iuf' and var.size:
                    sample=var.isel({dim:slice(0,min(int(ds.sizes[dim]),100)) for dim in var.dims}).values
                    import numpy as np
                    arr=np.asarray(sample,dtype='float64'); arr=arr[np.isfinite(arr)]
                    item['preview_stats']={'sampled_valid':int(arr.size),'min':float(arr.min()) if arr.size else None,'max':float(arr.max()) if arr.size else None,'mean':float(arr.mean()) if arr.size else None}
                variables.append(item)
            result.update({'dimensions':{k:int(v) for k,v in ds.sizes.items()},'variables':variables,'global_attributes':{str(k):str(v)[:300] for k,v in list(ds.attrs.items())[:30]}})
    elif suffix in ('.tif','.tiff'):
        import rasterio
        with rasterio.open(path) as src:
            bands=[]
            for i in range(1,min(src.count,30)+1):
                st=src.statistics(i,approx=True)
                bands.append({'band':i,'min':st.min,'max':st.max,'mean':st.mean,'std':st.std,'nodata':src.nodata})
            result.update({'crs':str(src.crs),'width':src.width,'height':src.height,'bands':bands,'bounds':list(src.bounds),'transform':list(src.transform)[:6]})
    else:
        result['note']='File type downloaded successfully; this release provides metadata inspection for CSV, JSON, HDF5, NetCDF and GeoTIFF.'
    return result
