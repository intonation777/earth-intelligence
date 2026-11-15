"""Inbound rate limiting for our own API endpoints.

Fixed-window counter per client IP, backed by the Django cache.
Returns HTTP 429 with Retry-After when the limit is exceeded.
"""
import time
from functools import wraps

from django.core.cache import cache
from django.http import JsonResponse


def client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', 'unknown')


def rate_limit(max_requests=60, window=60, scope='api'):
    """Decorator: allow ``max_requests`` per ``window`` seconds per IP per scope."""
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            ip = client_ip(request)
            now = time.time()
            window_id = int(now // window)
            key = f'rl:in:{scope}:{ip}:{window_id}'
            count = cache.get(key, 0)
            if count >= max_requests:
                retry = int(window - (now % window)) + 1
                resp = JsonResponse(
                    {'error': 'Rate limit exceeded', 'retry_after': retry},
                    status=429)
                resp['Retry-After'] = str(retry)
                return resp
            cache.set(key, count + 1, timeout=window + 5)
            return view(request, *args, **kwargs)
        return wrapper
    return decorator
