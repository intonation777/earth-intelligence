"""Server-side FAOSTAT client. No synthetic values are ever returned."""
import re
from datetime import datetime, timezone
import requests
from django.conf import settings
from django.core.cache import cache
from .http import fetch_json, DataSourceError

FAO_BASES = (
    "https://fenixservices.fao.org/faostat/api/v1/en/data/QCL",
    "https://faostatservices.fao.org/api/v1/en/data/QCL",
)
IRAN_AREA_CODE = 102
ELEMENTS = {"2510": "production", "2312": "area", "2413": "yield"}
CROPS = [
    {"key":"wheat","name_fa":"گندم","name_en":"Wheat","item_code":15},
    {"key":"barley","name_fa":"جو","name_en":"Barley","item_code":44},
    {"key":"rice","name_fa":"برنج (شلتوک)","name_en":"Rice, paddy","item_code":27},
    {"key":"maize","name_fa":"ذرت دانه‌ای","name_en":"Maize","item_code":56},
    {"key":"potato","name_fa":"سیب‌زمینی","name_en":"Potatoes","item_code":116},
    {"key":"tomato","name_fa":"گوجه‌فرنگی","name_en":"Tomatoes","item_code":388},
    {"key":"sugarbeet","name_fa":"چغندرقند","name_en":"Sugar beet","item_code":157},
    {"key":"dates","name_fa":"خرما","name_en":"Dates","item_code":577},
    {"key":"pistachio","name_fa":"پسته","name_en":"Pistachios","item_code":223},
]

def _pick(row, *keys):
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None

def _parse(payload):
    rows = payload.get("data", payload.get("Data", [])) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("ساختار پاسخ FAOSTAT قابل شناسایی نیست")
    result = {name: [] for name in ELEMENTS.values()}
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(_pick(row, "Element Code", "element_code", "ElementCode") or "")
        element = ELEMENTS.get(code)
        if not element:
            name = str(_pick(row, "Element", "element") or "").lower()
            element = next((v for k,v in (("production","production"),("area","area"),("yield","yield")) if name.startswith(k)), None)
        year = _pick(row, "Year", "year")
        value = _pick(row, "Value", "value")
        try:
            year, value = int(year), float(str(value).replace(",", ""))
        except (TypeError, ValueError):
            continue
        if element and year > 0:
            source_unit = str(_pick(row, "Unit", "unit") or "")
            output_unit = source_unit
            if element == "yield":
                normalized = source_unit.lower().replace(" ", "")
                if normalized in ("hg/ha", "hg/ha/yr"):
                    value /= 10000.0
                    output_unit = "tonnes/ha"
                elif normalized in ("kg/ha", "kg/ha/yr"):
                    value /= 1000.0
                    output_unit = "tonnes/ha"
                elif normalized in ("t/ha", "tonnes/ha", "tonne/ha"):
                    output_unit = "tonnes/ha"
            area_code = _pick(row, "Area Code", "area_code", "AreaCode")
            area_name = _pick(row, "Area", "area")
            result[element].append({"year": year, "value": value,
                                    "unit": output_unit, "source_unit": source_unit,
                                    "area_code": str(area_code) if area_code is not None else None,
                                    "area": str(area_name) if area_name else None})
    for key in result:
        result[key].sort(key=lambda x: x["year"])
    if not any(result.values()):
        raise ValueError("FAOSTAT برای این محصول داده قابل استفاده برنگرداند")
    return result

def _request_faostat(params):
    """Try both FAOSTAT endpoints; return parsed payload or raise RuntimeError."""
    errors = []
    headers = {}
    api_key = getattr(settings, "FAO_API_KEY", "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    for base in FAO_BASES:
        try:
            payload = fetch_json(base, params=params, headers=headers,
                                 timeout=getattr(settings, "FAO_TIMEOUT", 30),
                                 max_retries=1, backoff=1.5, source='FAOSTAT')
            return payload, base
        except (DataSourceError, ValueError, TypeError) as exc:
            errors.append(f"{base}: {exc}")
    raise RuntimeError("دریافت زنده FAOSTAT ناموفق بود؛ داده نمونه جایگزین نشده است. " + " | ".join(errors))


def fetch_crop(crop_key, force=False, area_code=IRAN_AREA_CODE):
    crop = next((x for x in CROPS if x["key"] == crop_key), None)
    if not crop:
        raise ValueError("محصول انتخاب‌شده پشتیبانی نمی‌شود")
    cache_key = f"faostat:qcl:{area_code}:{crop_key}:v1"
    if not force:
        cached = cache.get(cache_key)
        if cached:
            return cached
    params = {"area": area_code, "item": crop["item_code"],
              "element": "2510,2312,2413", "area_cs": "FAO", "item_cs": "FAO",
              "show_codes": "true", "show_unit": "true", "null_values": "false",
              "page_size": 5000, "output_type": "json"}
    payload, base = _request_faostat(params)
    series = _parse(payload)
    result = {"source":"FAOSTAT", "domain":"QCL", "area":"Iran" if area_code == IRAN_AREA_CODE else f"area:{area_code}",
              "area_code":area_code, "item":crop, "series":series,
              "source_url":requests.Request('GET', base, params=params).prepare().url,
              "retrieved_from":"official_api",
              "fetched_at":datetime.now(timezone.utc).isoformat(),
              "cache_ttl_seconds":21600,
              "provenance": _fao_crop_provenance(crop["key"], area_code)}
    try:
        from .provenance_store import record_snapshot
        record_snapshot('faostat', 'fao_qcl_iran', f'{crop["key"]}:{area_code}',
                        result['provenance'], payload_ref=result['source_url'],
                        metadata={'crop': crop['key'], 'area_code': area_code})
    except Exception:
        pass
    cache.set(cache_key, result, 21600)
    return result


def _fao_crop_provenance(crop_key, area_code):
    """Data Contract envelope for FAOSTAT Iran crop series (Phase 1)."""
    from .data_contract import DataContract, validate_contract, quality_from_issues
    c = DataContract.now(
        source='FAOSTAT', dataset_id='fao_qcl_iran', kind='statistics',
        parameter=crop_key, original_unit='mixed',
        normalized_unit='tonnes / hectares',
        temporal_resolution='annual', spatial_resolution='country',
        limitations=['National annual statistics — not field-level measurements.'],
        metadata={'area_code': area_code, 'domain': 'QCL'})
    issues = validate_contract(c)
    return {**c.to_dict(), 'quality_issues': issues, 'quality_status': quality_from_issues(issues)}


def fetch_world(crop_key, element="production", top=10):
    """All-area FAOSTAT query → ranking + Iran position + top-producer series.

    No hardcoded country codes: ranking is derived from the live all-areas
    response, so it stays correct even if FAO area codes change.
    """
    crop = next((x for x in CROPS if x["key"] == crop_key), None)
    if not crop:
        raise ValueError("محصول انتخاب‌شده پشتیبانی نمی‌شود")
    element_code = {"production": "2510", "area": "2312", "yield": "2413"}.get(element)
    if not element_code:
        raise ValueError("شاخص نامعتبر است")
    cache_key = f"faostat:qcl:world:{crop_key}:{element}:v1"
    cached = cache.get(cache_key)
    if cached:
        return cached
    params = {"item": crop["item_code"], "element": element_code,
              "area_cs": "FAO", "item_cs": "FAO",
              "show_codes": "true", "show_unit": "true", "null_values": "false",
              "page_size": 5000, "output_type": "json"}
    payload, base = _request_faostat(params)
    parsed = _parse(payload)
    rows = parsed.get(element, [])
    if not rows:
        raise ValueError("FAOSTAT برای این محصول داده جهانی قابل استفاده برنگرداند")
    # latest year per area
    latest = {}
    for r in rows:
        ac = r.get("area_code")
        if ac is None:
            continue
        if ac not in latest or r["year"] > latest[ac]["year"]:
            latest[ac] = r
    ranking = sorted(latest.values(), key=lambda x: x["value"], reverse=True)
    iran = next((r for r in ranking if r.get("area_code") == str(IRAN_AREA_CODE)), None)
    iran_rank = ranking.index(iran) + 1 if iran else None
    top_rows = ranking[:top]
    # comparison series: top producers + Iran, all years
    wanted = {r["area_code"] for r in top_rows} | ({str(IRAN_AREA_CODE)} if iran else set())
    series = {}
    for r in rows:
        ac = r.get("area_code")
        if ac in wanted:
            series.setdefault(ac, {"area": r.get("area"), "points": []})["points"].append(
                {"year": r["year"], "value": r["value"], "unit": r["unit"]})
    for ac in series:
        series[ac]["points"].sort(key=lambda p: p["year"])
    result = {"source": "FAOSTAT", "domain": "QCL", "scope": "world",
              "item": crop, "element": element,
              "ranking": [{"rank": i + 1, "area_code": r.get("area_code"),
                           "area": r.get("area"), "year": r["year"],
                           "value": r["value"], "unit": r["unit"],
                           "is_iran": r.get("area_code") == str(IRAN_AREA_CODE)}
                          for i, r in enumerate(ranking)],
              "iran": {"rank": iran_rank, "area": iran.get("area") if iran else None,
                       "year": iran["year"] if iran else None,
                       "value": iran["value"] if iran else None,
                       "unit": iran["unit"] if iran else None} if iran else None,
              "comparison": series,
              "source_url": requests.Request('GET', base, params=params).prepare().url,
              "retrieved_from": "official_api",
              "fetched_at": datetime.now(timezone.utc).isoformat(),
              "cache_ttl_seconds": 21600,
              "provenance": _fao_provenance(crop, element)}
    try:
        from .provenance_store import record_snapshot
        record_snapshot('faostat', 'fao_qcl_world', f'{crop}/{element}',
                        result['provenance'], payload_ref=result['source_url'],
                        metadata={'crop': crop, 'element': element})
    except Exception:
        pass
    cache.set(cache_key, result, 21600)
    return result


def _fao_provenance(crop, element):
    """Data Contract envelope for FAOSTAT responses (Phase 1)."""
    from .data_contract import DataContract, validate_contract, quality_from_issues
    c = DataContract.now(
        source='FAOSTAT', dataset_id='fao_qcl_world', kind='statistics',
        parameter=f'{crop}/{element}', original_unit='mixed',
        normalized_unit='tonnes / hectares',
        temporal_resolution='annual', spatial_resolution='country',
        limitations=['National annual statistics — not field-level measurements.'],
        metadata={'domain': 'QCL'})
    issues = validate_contract(c)
    return {**c.to_dict(), 'quality_issues': issues, 'quality_status': quality_from_issues(issues)}
