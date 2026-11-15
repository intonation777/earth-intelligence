"""Request observability middleware — request IDs, timing, redacted paths, metrics."""
import logging
import re
import time
import uuid
from urllib.parse import parse_qsl

from .services.monitoring import record_request

logger = logging.getLogger('core.request')

_SENSITIVE = re.compile(r'key|token|secret|password|api|authorization|credential|signature', re.I)
_SAFE_RID = re.compile(r'^[A-Za-z0-9._-]{8,64}$')


def redact_path(request):
    """Return path + query with sensitive parameters redacted."""
    qs = request.META.get('QUERY_STRING', '')
    if not qs:
        return request.path
    pairs = []
    for k, v in parse_qsl(qs, keep_blank_values=True):
        pairs.append((k, 'REDACTED' if _SENSITIVE.search(k) else v))
    return request.path + '?' + '&'.join(f'{k}={v}' for k, v in pairs)


def _normalize_path(path):
    return re.sub(r'/\d+(?=/|$)', '/{id}', path)


def _client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', 'unknown')


class RequestIDMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        rid = request.headers.get('X-Request-ID', '')
        request.request_id = rid if _SAFE_RID.match(rid or '') else uuid.uuid4().hex
        start = time.perf_counter()
        try:
            response = self.get_response(request)
        except Exception as exc:
            self._finish(request, start, 500, error=type(exc).__name__)
            raise
        status = getattr(response, 'status_code', 500)
        self._finish(request, start, status)
        response['X-Request-ID'] = request.request_id
        return response

    def _finish(self, request, start, status, error=None):
        duration_ms = int((time.perf_counter() - start) * 1000)
        path = redact_path(request)
        farmer_id = getattr(getattr(request, 'farmer', None), 'id', None)
        record_request(request.method, _normalize_path(request.path), status, duration_ms)
        level = logging.ERROR if status >= 500 else (logging.WARNING if status >= 400 else logging.INFO)
        logger.log(level, 'http_request', extra={
            'request_id': request.request_id,
            'method': request.method,
            'path': path,
            'status': status,
            'duration_ms': duration_ms,
            'client_ip': _client_ip(request),
            'user_agent': (request.META.get('HTTP_USER_AGENT') or '')[:120],
            'farmer_id': farmer_id,
            'error': error,
        })
