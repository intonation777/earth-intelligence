"""Place search adapter — OSM Nominatim forward geocoding.

Transport goes through the shared Data Integration Layer (services.http)
so retries, rate limiting, caching and SSRF validation are enforced.
"""
from django.core.cache import cache

from .http import fetch_json, DataSourceError

NOMINATIM_URL = 'https://nominatim.openstreetmap.org/search'
CACHE_TTL = 60 * 60 * 24  # 24 h


def search_places(query, limit=6):
    """Forward geocode a place name via OSM Nominatim. Returns list of {lat, lon, display_name, type}."""
    query = (query or '').strip()
    if len(query) < 3:
        raise ValueError('Search query must be at least 3 characters')
    cache_key = f'geocode:{query.lower()[:80]}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        payload = fetch_json(
            NOMINATIM_URL,
            params={'format': 'json', 'q': query, 'limit': limit, 'addressdetails': 1},
            headers={'User-Agent': 'nasa-unified-observatory/1.0 (research dashboard)'},
            timeout=20,
            max_retries=2,
            backoff=1.5,
            min_interval=1.1,  # Nominatim usage policy: max 1 req/s
            source='Nominatim',
        )
    except DataSourceError as exc:
        raise ValueError(f'Place search failed: {exc}') from exc
    items = []
    for entry in (payload or [])[:limit]:
        try:
            lat, lon = float(entry['lat']), float(entry['lon'])
        except (KeyError, TypeError, ValueError):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        items.append({
            'lat': lat,
            'lon': lon,
            'display_name': entry.get('display_name', ''),
            'type': entry.get('type', ''),
            'class': entry.get('category', ''),
        })
    cache.set(cache_key, items, CACHE_TTL)
    return items
