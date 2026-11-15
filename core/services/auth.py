"""Shared account gate for Earth Intelligence APIs.

Reuses the farmer account/session layer for now; role separation can be
added later without changing this decorator's contract.
"""
from django.http import JsonResponse

from farmer.services import get_farmer


def get_account(request):
    return get_farmer(request)


def require_account(view):
    """Require any authenticated platform account (session or api_key)."""
    def wrapper(request, *args, **kwargs):
        account = get_farmer(request)
        if account is None:
            return JsonResponse({'error': 'ورود به حساب کاربری لازم است'}, status=401)
        request.account = account
        request.farmer = account
        return view(request, *args, **kwargs)
    wrapper.__name__ = view.__name__
    return wrapper
