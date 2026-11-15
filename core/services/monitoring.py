"""Monitoring snapshot — request metrics, cache events, data freshness, DB latency."""
import time
from datetime import timedelta

from django.core.cache import cache
from django.db import connection
from django.utils import timezone

_TTL = 172800  # 48h


def _day():
    return timezone.now().strftime('%Y%m%d')


def _incr(key, amount=1):
    cache.add(key, 0, timeout=_TTL)
    try:
        cache.incr(key, amount)
    except ValueError:
        cache.set(key, amount, timeout=_TTL)


def _get_int(key):
    return int(cache.get(key, 0) or 0)


def record_request(method, path, status, duration_ms):
    base = f'metrics:{_day()}'
    _incr(f'{base}:requests')
    _incr(f'{base}:status:{status}')
    if status >= 500:
        _incr(f'{base}:errors')
    elif status >= 400:
        _incr(f'{base}:client_errors')
    _incr(f'{base}:latency_sum', int(duration_ms))
    _incr(f'{base}:latency_count')

    ep_key = f'{base}:endpoints'
    endpoints = cache.get(ep_key) or {}
    ep = f'{method} {path}'
    endpoints[ep] = endpoints.get(ep, 0) + 1
    if len(endpoints) > 100:
        endpoints = dict(sorted(endpoints.items(), key=lambda kv: -kv[1])[:50])
    cache.set(ep_key, endpoints, timeout=_TTL)


def record_cache_event(kind):
    _incr(f'metrics:{_day()}:cache:{kind}')


def record_tool_call(name, ok=True, ms=0):
    base = f'metrics:{_day()}:tools'
    _incr(f'{base}:calls')
    if not ok:
        _incr(f'{base}:errors')
    if name:
        _incr(f'{base}:by_name:{name[:80]}')


def _status_counts(base):
    out = {}
    for code in (200, 201, 204, 301, 302, 304, 400, 401, 403, 404, 409, 429, 500, 502, 503):
        n = _get_int(f'{base}:status:{code}')
        if n:
            out[str(code)] = n
    return out


def snapshot():
    base = f'metrics:{_day()}'
    total = _get_int(f'{base}:requests')
    latency_count = _get_int(f'{base}:latency_count')
    endpoints = cache.get(f'{base}:endpoints') or {}
    top_endpoints = sorted(endpoints.items(), key=lambda kv: -kv[1])[:10]

    cache_base = f'metrics:{_day()}:cache'
    cache_hits = _get_int(f'{cache_base}:hit')
    cache_stale = _get_int(f'{cache_base}:stale')
    cache_miss = _get_int(f'{cache_base}:miss')
    cache_total = cache_hits + cache_stale + cache_miss

    db_latency_ms = None
    db_ok = False
    try:
        t0 = time.perf_counter()
        with connection.cursor() as cur:
            cur.execute('SELECT 1')
            cur.fetchone()
        db_latency_ms = int((time.perf_counter() - t0) * 1000)
        db_ok = True
    except Exception:
        db_ok = False

    freshness = {'snapshots': 0, 'latest_retrieved_at': None, 'ingestion_errors_1h': 0}
    try:
        from core.models import DataSnapshot, DataIngestionLog
        latest = DataSnapshot.objects.order_by('-retrieved_at').values_list('retrieved_at', flat=True).first()
        freshness['snapshots'] = DataSnapshot.objects.count()
        freshness['latest_retrieved_at'] = latest.isoformat() if latest else None
        freshness['ingestion_errors_1h'] = DataIngestionLog.objects.filter(
            status='error', created_at__gte=timezone.now() - timedelta(hours=1)).count()
    except Exception:
        pass

    tools_base = f'metrics:{_day()}:tools'
    return {
        'generated_at': timezone.now().isoformat(),
        'requests': {
            'total': total,
            'errors_5xx': _get_int(f'{base}:errors'),
            'client_errors_4xx': _get_int(f'{base}:client_errors'),
            'error_rate': round(_get_int(f'{base}:errors') / total, 4) if total else 0.0,
            'avg_latency_ms': round(_get_int(f'{base}:latency_sum') / latency_count, 1) if latency_count else None,
            'status_counts': _status_counts(base),
            'top_endpoints': [{'endpoint': k, 'count': v} for k, v in top_endpoints],
        },
        'cache': {
            'hits': cache_hits, 'stale': cache_stale, 'misses': cache_miss,
            'hit_rate': round((cache_hits + cache_stale) / cache_total, 4) if cache_total else None,
        },
        'data_freshness': freshness,
        'database': {'ok': db_ok, 'latency_ms': db_latency_ms},
        'agent_tools': {
            'calls': _get_int(f'{tools_base}:calls'),
            'errors': _get_int(f'{tools_base}:errors'),
        },
    }
