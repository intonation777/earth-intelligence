"""Shared HTTP layer for all data-source adapters (Data Integration Layer).

Every external call in the project should go through ``fetch_json`` /
``fetch_bytes`` so that timeout, retry/backoff, rate limiting, caching,
response-size limits and SSRF/domain validation are enforced in one place.

Adapters (nasa.py, fao.py, geocode.py, ...) stay responsible for request
construction and response parsing; this module only handles transport.
"""
import time
from urllib.parse import urlparse

import requests
from django.core.cache import cache
from django.conf import settings

# Hosts that adapters are allowed to call. Extend per-source via
# settings.DATA_ALLOWED_HOSTS or per-call ``allowed_hosts``.
DEFAULT_ALLOWED_HOSTS = (
    'power.larc.nasa.gov',
    'cmr.earthdata.nasa.gov',
    'gibs.earthdata.nasa.gov',
    'firms.modaps.eosdis.nasa.gov',
    'nominatim.openstreetmap.org',
    'fenixservices.fao.org',
    'faostatservices.fao.org',
    'www.fao.org',
    'api.open-meteo.com',
    'archive-api.open-meteo.com',
)

MAX_BYTES = 25 * 1024 * 1024  # 25 MB JSON/text guard
RATE_LIMIT_CACHE_PREFIX = 'rl:'


class DataSourceError(Exception):
    """Raised when an upstream data source fails or returns unusable data."""

    def __init__(self, message, source='external', status=None):
        super().__init__(message)
        self.source = source
        self.status = status


def _allowed_hosts():
    extra = getattr(settings, 'DATA_ALLOWED_HOSTS', '') or ''
    hosts = set(DEFAULT_ALLOWED_HOSTS)
    hosts.update(h.strip().lower() for h in extra.split(',') if h.strip())
    return hosts


def validate_url(url, allowed_hosts=None):
    """SSRF guard: only https, only whitelisted hosts, no credentials in URL."""
    parsed = urlparse(url)
    if parsed.scheme != 'https':
        raise DataSourceError('Only HTTPS data sources are allowed', status=400)
    if parsed.username or parsed.password:
        raise DataSourceError('Credentials in data URLs are not allowed', status=400)
    host = (parsed.hostname or '').lower()
    allowed = {h.lower() for h in (allowed_hosts or _allowed_hosts())}
    if host not in allowed:
        raise DataSourceError(f'Host {host!r} is not in the allowed data-source list', status=400)
    return url


def _rate_limit(host, min_interval):
    """Simple per-host minimum-interval throttle backed by the Django cache."""
    if not min_interval:
        return
    key = RATE_LIMIT_CACHE_PREFIX + host
    now = time.time()
    last = cache.get(key)
    if last is not None and now - last < min_interval:
        time.sleep(min_interval - (now - last))
    cache.set(key, time.time(), timeout=60)


def _cb_open(host):
    return (cache.get(f'cb:{host}:open') or 0) > time.time()


def _cb_success(host):
    cache.delete(f'cb:{host}')
    cache.delete(f'cb:{host}:open')


def _cb_failure(host):
    fails = int(cache.get(f'cb:{host}') or 0) + 1
    cache.set(f'cb:{host}', fails, timeout=300)
    if fails >= 5:
        cache.set(f'cb:{host}:open', time.time() + 60, timeout=70)


def _request(url, *, method='GET', params=None, headers=None, data=None,
             timeout=30, max_retries=2, backoff=1.5, min_interval=0.0,
             max_bytes=MAX_BYTES, allowed_hosts=None, source='external'):
    validate_url(url, allowed_hosts)
    host = urlparse(url).hostname or ''
    if _cb_open(host):
        raise DataSourceError(f'{source} circuit open for {host}', source=source, status=503)
    _rate_limit(host, min_interval)
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            resp = requests.request(method, url, params=params, headers=headers,
                                    data=data, timeout=timeout, stream=True)
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < max_retries:
                    time.sleep(backoff ** attempt)
                    continue
                _cb_failure(host)
                raise DataSourceError(f'{source} returned HTTP {resp.status_code}',
                                      source=source, status=resp.status_code)
            if resp.status_code >= 400:
                raise DataSourceError(f'{source} returned HTTP {resp.status_code}',
                                      source=source, status=resp.status_code)
            chunks, total = [], 0
            for chunk in resp.iter_content(65536):
                total += len(chunk)
                if total > max_bytes:
                    raise DataSourceError(f'{source} response exceeded size limit',
                                          source=source, status=413)
                chunks.append(chunk)
            _cb_success(host)
            return b''.join(chunks), dict(resp.headers)
        except DataSourceError:
            raise
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < max_retries:
                time.sleep(backoff ** attempt)
                continue
            _cb_failure(host)
            raise DataSourceError(f'{source} request failed: {exc}',
                                  source=source) from exc
    raise DataSourceError(f'{source} request failed', source=source)


def fetch_json(url, *, cache_key=None, cache_ttl=None, return_headers=False, **kwargs):
    """GET JSON with optional Django-cache layer. Returns parsed object.

    With ``return_headers=True`` returns ``(payload, headers_dict)`` —
    needed for APIs like NASA CMR that paginate via response headers.
    """
    if cache_key and cache_ttl:
        cached = cache.get(cache_key)
        if cached is not None:
            try:
                from .provenance_store import log_fetch
                ts = cache.get(cache_key + ':ts')
                age = (time.time() - ts) if ts is not None else 0
                status = 'stale' if age > cache_ttl * 0.8 else 'cached'
                log_fetch(kwargs.get('source', 'external'), '', url, status=status)
                from .monitoring import record_cache_event
                record_cache_event('stale' if status == 'stale' else 'hit')
            except Exception:
                pass
            return (cached, {}) if return_headers else cached
    if cache_key and cache_ttl:
        try:
            from .monitoring import record_cache_event
            record_cache_event('miss')
        except Exception:
            pass
    _t0 = time.monotonic()
    try:
        body, headers = _request(url, **kwargs)
    except Exception as exc:
        try:
            from .provenance_store import log_fetch
            log_fetch(kwargs.get('source', 'external'), '', url, status='error',
                      duration_ms=int((time.monotonic() - _t0) * 1000),
                      error_message=str(exc)[:300])
        except Exception:
            pass
        raise
    try:
        from .provenance_store import log_fetch
        log_fetch(kwargs.get('source', 'external'), '', url, status='success',
                  duration_ms=int((time.monotonic() - _t0) * 1000))
    except Exception:
        pass
    import json
    try:
        payload = json.loads(body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError) as exc:
        raise DataSourceError('Upstream returned invalid JSON', source=kwargs.get('source', 'external')) from exc
    if cache_key and cache_ttl:
        cache.set(cache_key, payload, timeout=cache_ttl)
        cache.set(cache_key + ':ts', time.time(), timeout=cache_ttl)
    return (payload, headers) if return_headers else payload


def fetch_bytes(url, *, cache_key=None, cache_ttl=None, **kwargs):
    """GET raw bytes with optional Django-cache layer."""
    if cache_key and cache_ttl:
        cached = cache.get(cache_key)
        if cached is not None:
            try:
                from .provenance_store import log_fetch
                ts = cache.get(cache_key + ':ts')
                age = (time.time() - ts) if ts is not None else 0
                status = 'stale' if age > cache_ttl * 0.8 else 'cached'
                log_fetch(kwargs.get('source', 'external'), '', url, status=status)
                from .monitoring import record_cache_event
                record_cache_event('stale' if status == 'stale' else 'hit')
            except Exception:
                pass
            return cached
    if cache_key and cache_ttl:
        try:
            from .monitoring import record_cache_event
            record_cache_event('miss')
        except Exception:
            pass
    _t0 = time.monotonic()
    try:
        body, _ = _request(url, **kwargs)
    except Exception as exc:
        try:
            from .provenance_store import log_fetch
            log_fetch(kwargs.get('source', 'external'), '', url, status='error',
                      duration_ms=int((time.monotonic() - _t0) * 1000),
                      error_message=str(exc)[:300])
        except Exception:
            pass
        raise
    try:
        from .provenance_store import log_fetch
        log_fetch(kwargs.get('source', 'external'), '', url, status='success',
                  duration_ms=int((time.monotonic() - _t0) * 1000))
    except Exception:
        pass
    if cache_key and cache_ttl:
        cache.set(cache_key, body, timeout=cache_ttl)
        cache.set(cache_key + ':ts', time.time(), timeout=cache_ttl)
    return body
