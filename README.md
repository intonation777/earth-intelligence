# NASA Earth Intelligence Platform

**Earth & Climate Observatory + Farmer Assistant** — a bilingual (Persian/English) Django platform that turns NASA Earth-observation data into actionable climate insight and farm-level decision support.

Built for the **NASA International Space Apps Challenge**.

> Independent research tool — not an official NASA product. NASA data remain subject to each provider's terms, citation requirements, latency, quality flags and access restrictions.

## Live demo

- Interactive demo: **https://nasa-earth-observatory.onrender.com** (public, no login required — demo mode gives each visitor an isolated sandbox account)
- Presentation (7 slides): [`docs/demo/earth intelligence platform.pdf`](docs/demo/earth%20intelligence%20platform.pdf)
- Screenshots: [`docs/screenshots/`](docs/screenshots/)

## Problem

Earth-observation data is powerful but inaccessible to the people who need it most: farmers deciding irrigation today, and citizens/researchers trying to understand local climate. Raw NASA products require specialist tools, credentials and domain knowledge.

## Solution

One platform, two modules:

### 1. Climate Research — Earth & Climate Observatory (`/observatory/`)

- **NASA POWER live API** — point weather/climate series at hourly, daily, monthly and climatology levels (AG/RE/SB/HY communities, up to 20 parameters/request), bilingual parameter metadata, charts, CSV export.
- **NASA CMR catalogue** — live search across NASA Earthdata collections; collection detail, granule search with time/bbox filters.
- **Granule download** — server-side streaming with HTTPS/domain allow-list, size limit, optional Earthdata bearer token.
- **File inspection** — CSV/JSON/GeoJSON/HDF5/NetCDF/GeoTIFF structure inspection (scientific readers optional).
- **Satellite map layers (GIBS/WMTS)** — MODIS Terra/Aqua true-color, NDVI, EVI, land-surface temperature (day/night), monthly NDVI, and **SMAP soil moisture** — rendered on an interactive Leaflet map with date selection.
- **Climate indicators & reports** — derived indicators, charts, exportable PDF climate report.
- **Bilingual AI assistant** — rule-based agent answering questions about NASA data, FAO crops and farm practice in Persian and English (no fabricated science — honest capability reporting).
- **Bilingual FAQ**, saved/reproducible analyses with CSV/PDF export.

### 2. Farmer Assistant (`/farmer/`)

- Farm → field → crop-cycle management with lifecycle calendar.
- Soil profiles, water sources, irrigation advice, fertilizer records.
- Field observations with photo upload and symptom-based diagnosis.
- Risk alerts (weather/crop stress), prioritized tasks, daily briefing.
- Farm economics: expenses, yield/price scenarios.
- Bilingual assistant with auditable tool calls.

## NASA & open data sources

| Source | Use |
|---|---|
| NASA POWER API | Weather/climate time series |
| NASA CMR (Earthdata Search) | Dataset/granule discovery |
| NASA GIBS (WMTS) | MODIS + SMAP satellite layers |
| Earthdata Login (optional token) | Access to restricted granules |
| FAO FAOSTAT | Crop reference data |
| OpenStreetMap Nominatim + tiles | Geocoding and basemap |

## Architecture

```
Browser (bilingual FA/EN UI, Leaflet + Chart.js)
        │  JSON APIs (/api/* and /api/v1/*)
        ▼
Django 5.2 ── config/ (settings, urls, wsgi/asgi)
   ├── core/    Observatory: services/nasa.py (POWER, CMR, GIBS),
   │            fao.py, climate.py, agent.py, report.py, advice.py
   └── farmer/  Farm management: models (22), services, bilingual agent tools
        │
        ▼
SQLite (dev) / PostgreSQL (prod via DATABASE_URL)
Static: WhiteNoise   Server: Gunicorn
```

- Custom lightweight auth: session + `X-Farmer-Key` api_key; per-owner data isolation.
- `PUBLIC_DEMO=1` mode provisions an isolated demo account per browser session — used only on the public demo deployment.
- Rate limiting, request-id JSON logging, Prometheus-style `/api/metrics/`, `/api/health/?deep=1`.
- 179 automated tests (`manage.py test`).

## Quick start (Windows)

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   :: fill DJANGO_SECRET_KEY
python manage.py migrate
python manage.py runserver
```

Open http://127.0.0.1:8000 — landing page is public; create a farmer account or enable `PUBLIC_DEMO=1` for instant demo access.

Optional scientific file readers (HDF5/NetCDF/GeoTIFF inspection):

```bat
pip install -r requirements-geospatial.txt
```

## Configuration

See [`.env.example`](.env.example). Key variables:

- `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_BEHIND_PROXY`
- `DATABASE_URL` — empty = SQLite; `postgres://user:pass@host:5432/db` for PostgreSQL
- `NASA_EARTHDATA_TOKEN`, `FAO_API_KEY` — optional; empty = public endpoints only
- `PUBLIC_DEMO` — `1` only for the public demo deployment

## Deploy (Render)

Blueprint-ready: [`render.yaml`](render.yaml) + [`build.sh`](build.sh) provision a free web service + PostgreSQL database. Set `NASA_EARTHDATA_TOKEN`/`FAO_API_KEY` as secret env vars.

## Testing

```bat
python manage.py check
python manage.py test        :: 179 tests — API contracts, auth isolation, agent tools, frontend smoke
```

## Limitations & attribution

- POWER/CMR/GIBS are live external services — availability and latency are outside our control; the UI reports upstream errors honestly.
- Satellite layers are visual/contextual; quantitative claims require per-product QA (documented in-app).
- No fabricated data: missing values are shown as missing, never interpolated silently.
- Data providers: NASA POWER, NASA CMR/Earthdata, NASA GIBS, SMAP, MODIS, FAO FAOSTAT, OpenStreetMap. See each provider's terms for citation.

## License

MIT — see repository for details.
