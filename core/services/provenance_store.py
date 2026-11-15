"""Persistence helpers for Data Intelligence Infrastructure (Phase 2).

Every external fetch is logged to DataIngestionLog; every successful
scientific payload can be snapshotted to DataSnapshot with its
DataContract provenance. All helpers are fail-safe — a logging or DB
error must never break the data pipeline.
"""
import time


def _get_or_create_source(key, name='', base_url=''):
    from core.models import DataSource
    src, _ = DataSource.objects.get_or_create(key=key, defaults={'name': name or key, 'base_url': base_url})
    return src


def _get_or_create_dataset(source, key, **kw):
    from core.models import Dataset
    ds, _ = Dataset.objects.get_or_create(source=source, key=key, defaults=kw)
    return ds


def log_fetch(source_key, dataset_key='', url='', status='success',
              http_status=None, duration_ms=None, error_message=''):
    """Write one DataIngestionLog row. Never raises."""
    try:
        from core.models import DataIngestionLog
        src = _get_or_create_source(source_key)
        DataIngestionLog.objects.create(
            source=src, dataset_key=dataset_key[:80], request_url=url[:500],
            status=status, http_status=http_status, duration_ms=duration_ms,
            error_message=(error_message or '')[:2000])
    except Exception:
        pass


def record_snapshot(source_key, dataset_key, request_key, contract_dict,
                    payload_ref='', observed_at=None, metadata=None):
    """Persist a DataSnapshot from a DataContract dict. Never raises.

    Returns the snapshot id or None.
    """
    try:
        from core.models import DataSnapshot
        from django.utils import timezone
        from django.utils.dateparse import parse_datetime
        from datetime import timedelta
        src = _get_or_create_source(source_key)
        ds = _get_or_create_dataset(src, dataset_key)
        # duplicate detection: same dataset+request_key within 1h → reuse
        dup = DataSnapshot.objects.filter(
            dataset=ds, request_key=request_key[:200],
            retrieved_at__gte=timezone.now() - timedelta(hours=1)).first()
        if dup is not None:
            return dup.id
        obs = parse_datetime(contract_dict.get('observed_at') or '') if contract_dict.get('observed_at') else None
        snap = DataSnapshot.objects.create(
            dataset=ds, request_key=request_key[:200],
            observed_at=obs,
            quality_status=contract_dict.get('quality_status', 'valid'),
            limitations=contract_dict.get('limitations') or [],
            metadata=metadata or {k: contract_dict.get(k) for k in
                                  ('source', 'dataset_id', 'kind', 'parameter',
                                   'original_unit', 'normalized_unit', 'lat', 'lon',
                                   'temporal_resolution', 'spatial_resolution')},
            payload_ref=payload_ref[:300])
        return snap.id
    except Exception:
        return None


def timed_fetch_log(source_key, dataset_key, url, fn, *args, **kwargs):
    """Wrap a fetch callable: log success/error + duration. Returns fn result."""
    t0 = time.monotonic()
    try:
        result = fn(*args, **kwargs)
        log_fetch(source_key, dataset_key, url, status='success',
                  duration_ms=int((time.monotonic() - t0) * 1000))
        return result
    except Exception as exc:
        log_fetch(source_key, dataset_key, url, status='error',
                  duration_ms=int((time.monotonic() - t0) * 1000),
                  error_message=str(exc)[:500])
        raise
