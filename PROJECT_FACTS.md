# PROJECT_FACTS — NASA Unified Earth & Climate Observatory (Django v2.1.0)

**Purpose:** verified facts for slide preparation. Every claim below was checked directly in the source code on 2026‑11‑14, or measured by running the app/tests. Anything not provable is marked `[UNVERIFIED]`.
**Project root:** `nasa_unified/` (Django project). Server used for verification: `python manage.py runserver 0.0.0.0:8000 --noreload` at `http://127.0.0.1:8000`.

---

## A. Real numbers

### Tests
- **Command:** `python manage.py test` (Django 5.2 test runner)
- **Result (run on 2026‑11‑14):** `Ran 179 tests in 158.035s` — **OK, 0 failures, 0 errors**
- Breakdown by file (counted by `def test_` in source):
  | File | Tests |
  |---|---|
  | `core/tests.py` | 57 |
  | `core/tests_frontend.py` | 16 |
  | `core/tests_observability.py` | 3 |
  | `core/tests_simulation.py` | 3 |
  | `farmer/tests.py` | 100 |
  | **Total** | **179** |

### Runtime versions (measured in the running environment)
- Python **3.11.0**, Django **5.2.17**, requests **2.34.2**, python‑dotenv **1.2.4**, reportlab **5.1.0**
- **Declared** in `requirements.txt`: `Django>=5.2,<5.3`, `requests>=2.32,<3`, `python-dotenv>=1.0,<2` (3 packages)
- `requirements-geospatial.txt` (optional readers): pandas≥2.2, numpy≥2.0, h5py≥3.12, xarray≥2024.10, netCDF4≥1.7, rasterio≥1.4
- Honest note: **reportlab is used by code (`core/services/report.py`) but is NOT declared in requirements.txt** — it is installed in this environment (v5.1.0). In this environment pandas (3.0.5) and numpy (2.3.5) are installed, but **h5py / xarray / netCDF4 / rasterio are NOT installed** — so HDF5/NetCDF/GeoTIFF inspection returns HTTP 501 "Optional data reader is not installed" (`core/views.py inspect_file`); CSV/JSON inspection works.

### Endpoints (`config/urls.py`, all verified by reading the file)
- **70 route patterns total**: 3 page routes + **67 API endpoints**
- Lines 79–82 additionally mirror **every** `/api/*` route as `/api/v1/*` → **137 route patterns** registered in total
- Page routes: `/` (landing), `/observatory/` (Earth Intelligence dashboard), `/farmer/` (Farmer Assistant)
- The 67 API endpoints (grouped):
  - **System (2):** `api/health/`, `api/metrics/`
  - **NASA (7):** `api/power/`, `api/power/parameters/`, `api/catalog/`, `api/granules/`, `api/download/`, `api/inspect/`, `api/collections/<concept_id>/`
  - **Science (8):** `api/climate/`, `api/advice/`, `api/report/climate/`, `api/agent/`, `api/geocode/`, `api/timeseries/`, `api/analyses/save/|/|<id>/|<id>/delete/|<id>/reproduce/|<id>/export/` (7 analysis routes), `api/data-quality/`
  - **FAO (3):** `api/fao/crops/`, `api/fao/crops/<crop_key>/`, `api/fao/world/<crop_key>/`
  - **FAQ (1):** `api/faq/`
  - **Farmer auth (4):** `api/farmer/register/`, `api/farmer/login/`, `api/farmer/logout/`, `api/farmer/me/`
  - **Farmer profile/farm (4):** `api/farmer/profile/`, `api/farmer/profile/get/`, `api/farmer/farms/`, `api/farmer/farms/create/`
  - **Fields & soil (7):** `api/farmer/fields/`, `api/farmer/fields/create/`, `api/farmer/fields/<id>/`, `api/farmer/fields/<id>/update/`, `api/farmer/fields/<id>/soil/`, `api/farmer/fields/<id>/soil/get/`, `api/farmer/farms/<farm_id>/water-sources/` + `…/list/` (counted as 7 with both water-source routes)
  - **Crop engines (6):** `api/farmer/crops/`, `api/farmer/recommend/`, `api/farmer/cycles/create/`, `api/farmer/cycles/`, `api/farmer/calendar/`, `api/farmer/irrigation/`
  - **Daily & tasks (4):** `api/farmer/daily/`, `api/farmer/tasks/`, `api/farmer/tasks/create/`, `api/farmer/tasks/<id>/done/`
  - **Risk & diagnosis (3):** `api/farmer/risks/`, `api/farmer/observe/` (image upload), `api/farmer/diagnose/`
  - **Economics (3):** `api/farmer/economics/`, `api/farmer/expenses/`, `api/farmer/expenses/create/`
  - **Agent (3):** `api/farmer/agent/`, `api/farmer/agent/tools/`, `api/farmer/agent/tool/`
  - **Operations & decision (6):** `api/farmer/operations/`, `api/farmer/recommendations/`, `api/farmer/recommendations/<id>/feedback/`, `api/farmer/alerts/`, `api/farmer/alerts/<id>/`, `api/farmer/alerts/<id>/action/`

### Data models
- **Farmer Assistant: 16 models** (`farmer/models.py`): `FarmerProfile`, `Farm`, `Field`, `SoilProfile`, `WaterSource`, `CropProfile`, `CropCycle`, `GrowthStage`, `FarmObservation`, `IrrigationRecord`, `FertilizerRecord`, `FarmTask`, `RiskAlert`, `Recommendation`, `HarvestRecord`, `FarmExpense`
- **Core: 5 models** (`core/models.py`): `DataSource`, `Dataset`, `SavedAnalysis`, `DataSnapshot`, `DataIngestionLog`
- Management commands: `seed_crops` (12 FAO‑reference crops), `db_backup` (SQLite backup / pg_dump), `db_verify`, `refresh_data`

---

## B. NASA and non‑NASA services actually called in code

| Service | Status | File / function | Input → output | Used by (product feature) |
|---|---|---|---|---|
| **NASA POWER** | **Used in code** | `core/services/nasa.py` → `fetch_power()`; called by `core/services/climate.py`, `core/services/advice.py`, `farmer/services/et0.py`, `farmer/services/lifecycle.py`, `farmer/services/tools.py`, `core/services/science_tools.py`; HTTP: `GET /api/power/` | lat/lon + YYYYMMDD range + parameter codes (T2M, T2M_MAX/MIN, PRECTOTCORR, RH2M, WS10M, ALLSKY_SFC_SW_DWN, T2MDEW, PS, EVPTRNS) + temporal (hourly/daily/monthly/climatology) + community (AG/RE/SB/HY) → daily/monthly time series with provenance | Climate Engine (SPI/SPEI/heatwave…), Agricultural Advisor, Farmer Irrigation (ET₀), Crop Lifecycle (GDD), observatory charts |
| **NASA CMR** | **Used in code** | `core/services/nasa.py` → `search_collections()`, `search_granules()` (UMM‑JSON, temporal/spatial filters, `CMR-Search-After` cursor deep paging); HTTP: `GET /api/catalog/`, `GET /api/granules/`, `GET /api/collections/<id>/` | keyword/provider/bbox/time → collection & granule metadata (not data values) | Observatory "Data Catalog" tab; agent `satellite_search` / `get_scientific_datasets` tool |
| **NASA GIBS** | **Used — frontend only** | `core/static/core/app.js` `SAT_LAYERS` (line 48) renders WMTS tiles from `https://gibs.earthdata.nasa.gov/wmts/epsg3857/...` directly in the browser (Leaflet) | Layer + date → map tiles | Observatory "Satellite Layers" tab (8 layers, incl. two‑date comparison). Backend host is allow‑listed in `core/services/http.py` but **no backend fetch of GIBS data exists** |
| **Earthdata Login (token)** | **Used in code (optional)** | `core/services/nasa.py` → `download_nasa_file()` sends `NASA_EARTHDATA_TOKEN` from settings as `Authorization: Bearer` | protected granule URLs → streamed file to `media/nasa_downloads` | "Download via app" on granules; token optional (unprotected granules need none) |
| **SMAP** | **Discoverable / tile layer only** | GIBS layer `SMAP_L3_Passive_Day_Soil_Moisture` (app.js SAT_LAYERS); discoverable via CMR catalog search. No SMAP‑specific science processing (README §"Important scientific and scope notes" #2) | — | Satellite layers map; catalog search |
| **MODIS** | **Discoverable / tile layer only** | GIBS layers: `MODIS_Terra_CorrectedReflectance_TrueColor`, `MODIS_Terra_NDVI_8Day`, `MODIS_Terra_EVI_8Day`, `MODIS_Terra_L3_NDVI_Monthly`, `MODIS_Aqua_L3_EVI_16Day`, `MODIS_Terra_L3_Land_Surface_Temp_Daily_Day`, `MODIS_Aqua_L3_Land_Surface_Temp_Daily_Night` (app.js SAT_LAYERS); discoverable via CMR | — | Satellite layers map (NDVI/EVI/LST/TrueColor + two‑date compare); catalog search |
| **FAOSTAT** | **Used in code** | `core/services/fao.py` → `fetch_crop()`, `fetch_world()` (dual API bases, 6‑hour cache); HTTP: `GET /api/fao/crops/<crop>/`, `GET /api/fao/world/<crop>/` | domain **QCL**, Iran area_code **102**, elements 2510/2312/2413 (production/area/yield), 9 crops → annual tonnes, hectares, tonnes/ha; world ranking | FAO Intelligence tab; fused with POWER in Agricultural Advisor (`core/services/advice.py`) |
| **OSM Nominatim** | **Used in code** | `core/services/geocode.py` → `search_places()` (24 h cache, 1.1 s rate limit, custom User‑Agent); HTTP: `GET /api/geocode/?q=` | place name → lat/lon candidates | Observatory place search; agent fuzzy location resolution (`core/services/agent.py`) |
| **Open‑Meteo** | **Not used** | hosts `api.open-meteo.com`, `archive-api.open-meteo.com` exist only in the SSRF allow‑list (`core/services/http.py` lines 28–29); **no code anywhere calls Open‑Meteo** | — | none |

---

## C. Claim checks

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| 1 | POWER hourly/daily/monthly/climatology + communities AG/RE/SB/HY | **Verified** | `core/services/nasa.py` (`fetch_power`, TEMPORAL + community params; monthly requests auto‑switch to community AG) |
| 2 | CMR collection & granule search, temporal/spatial filter, deep paging | **Verified** | `core/services/nasa.py` (`search_collections`, `search_granules`; UMM‑JSON, bbox/time, `CMR-Search-After` cursor) |
| 3 | Streaming download with Earthdata bearer token | **Verified** | `core/services/nasa.py` `download_nasa_file()` — streaming + `Authorization: Bearer` from `settings.NASA_EARTHDATA_TOKEN` (note: uses `requests` directly, not the shared http layer) |
| 4 | File inspection CSV, JSON/GeoJSON, HDF5, NetCDF, GeoTIFF | **Verified (code)** / **Partial (runtime)** | `core/services/nasa.py` `inspect_downloaded_file()`: CSV via pandas, JSON/GeoJSON, HDF5 via h5py, NetCDF via xarray, GeoTIFF via rasterio — all optional imports. In this environment h5py/xarray/netCDF4/rasterio are **not installed** → those formats return HTTP 501; CSV/JSON work |
| 5 | GIBS layers: True Color, NDVI, EVI, LST, SMAP soil moisture | **Verified** | `core/static/core/app.js` `SAT_LAYERS` — 8 WMTS layers incl. all five claimed (frontend‑only rendering; no backend GIBS fetch) |
| 6 | SPI (gamma), SPEI (log‑logistic), Hargreaves PET, heatwave, frost days, GDD, water balance, anomaly | **Verified** | `core/services/climate.py` (SPI gamma + method of moments; SPEI log‑logistic; Hargreaves FAO‑56 eq.50 PET; heatwave = ≥3 consecutive days Tmax ≥ 35 °C; frost days Tmin ≤ 0; GDD base 10 °C; P−PET; anomalies; per‑indicator limitations metadata) |
| 7 | FAO‑56 Penman–Monteith ET₀ from live POWER + Hargreaves fallback | **Verified** | `farmer/services/et0.py` (eq.47 u2, eq.38–40 Rn; `method='unavailable'` when inputs missing — never invents; fallback `et0_hargreaves`; used by `farmer/services/irrigation.py`) |
| 8 | POWER sentinel −999 → null | **Verified** | `core/services/nasa.py` line 73: `None if v == -999 else v` |
| 9 | SSRF guard: HTTPS‑only + domain allow‑list; timeout, exponential retry, rate limit, response size cap, cache, fetched_at | **Verified** | `core/services/http.py` — HTTPS‑only, host allow‑list, timeout, retry 1.5ⁿ backoff, per‑host rate limit, circuit breaker (5 fails → 60 s open), 25 MB cap, Django‑cache layer, provenance `log_fetch`, cache age → `cached`/`stale` status |
| 10 | PDF report (ReportLab, Persian font) + CSV | **Verified** | `core/services/report.py` (ReportLab, Tahoma font candidates, tested — PDF export test passed); CSV/PDF: `core/views.py` `export_analysis()` (`/api/analyses/<id>/export/?format=csv|pdf`); CSV export buttons in observatory UI |
| 11 | Farmer: Leaflet map, irrigation, crop lifecycle, risk, economics, confidence scoring, feedback loop, Simple/Expert, voice input, dark theme, offline status | **Verified** | Leaflet map: `farmer/templates/farmer/dashboard.html` + `farmer/static/farmer/farmer.js`; irrigation: `farmer/services/irrigation.py`; lifecycle: `farmer/services/lifecycle.py` (GDD); risk: `farmer/services/risk.py`; economics: `farmer/services/economics.py`; confidence: `Recommendation.confidence` + `farmer/services/decision.py` `compute_confidence()` (documented formula, capped 0.95); feedback loop: `record_feedback()` + `/api/farmer/recommendations/<id>/feedback/`; Simple/Expert: `mode-simple` body class + `farmer_agent.py` mode param; voice input: Web Speech API in `farmer.js` (browser‑dependent); dark theme: theme toggle; offline status: `navigator.onLine` handler in `farmer.js` |
| 12 | AI: bilingual intent routing (rule‑based vs LLM?), fuzzy location, tool whitelist, dedup & conflict resolution, symptom diagnosis with image upload | **Verified — all rule‑based, no LLM** | `core/services/agent_intents.py` (`resolve_intent` — keyword scoring, fa/en); fuzzy location `core/services/agent.py` (Nominatim candidates, strips question words); tool whitelist `core/services/tools.py` + `core/services/science_tools.py` + `farmer/services/tools.py` (schema validation, permission check, mutating tools require `confirm=true` → 409 preview); dedup/conflict: `farmer/services/decision.py` `_dedup_and_conflicts()` + `farmer/services/risk.py` fingerprint (SHA256 of field:kind) lifecycle; image upload stored as FarmObservation (`farmer/views.py` `observe_upload`, `farmer/services/diagnosis.py` `save_observation`) but **not analyzed by ML** — diagnosis maps text symptoms only, conservative, refers to expert |
| 13 | Any ML model or external LLM used? | **No** | `core/services/agent.py` docstring: "No external LLM is called"; `farmer/services/diagnosis.py`: "No ML model is connected"; `farmer/services/decision.py`: confidence "derived from real data completeness/freshness, not from an LLM". No ML library is imported anywhere in project code |
| 14 | What is on the roadmap / not yet implemented? | **Verified per item** | README has a production checklist, not a roadmap table. Status by item: **session auth — implemented** (`config/settings.py` SessionMiddleware + `farmer/views.py` farmer_login/register with password hashing); **`/api/v1/` — implemented** (`config/urls.py` lines 79–82 mirror); **PostgreSQL — optional support implemented** (`config/settings.py` accepts `DATABASE_URL=postgres://…`, default SQLite); **Celery / background jobs — not present** (no celery in project code or requirements); **push notification center — not present** (no SMS/email/push code; only the in‑app RiskAlert center with unread counts + status lifecycle is implemented); **FAO_API_KEY — setting exists** (`config/settings.py`), FAOSTAT endpoints used are public |

---

## D. Demo scenario (≈30 seconds, real pages and URLs)

1. **Landing:** open `http://127.0.0.1:8000/` — bilingual landing page (fa/en toggle button).
2. **Earth Intelligence:** click through to `/observatory/` (login required). In the "Place Search" box type a place (e.g. "Karaj") → Nominatim candidates → click one → coordinates set. Open the POWER analysis tab → real NASA POWER daily time series chart renders with a provenance badge (source, quality, retrieved‑at).
3. **Farmer Assistant:** open `http://127.0.0.1:8000/farmer/` — onboarding map (Leaflet): click the field location → register/login → field saved with crop.
4. **Decision:** the Daily view ("امروز چه کار کنم؟") shows for each field: growth stage (from GDD), irrigation advice **with net water need in mm and a confidence score**, and risk alerts (drought SPI‑6, heatwave) — each item lists its data source and limitations.
5. **Ask the agent:** type «آبیاری چقدر؟» in the agent box → routed to the irrigation engine → plain‑language answer with sources. English UI available on every page via the language button.

---

## E. Real limitations (say these honestly on slides)

1. All NASA POWER values are **gridded/model estimates, not field measurements** (stated in code limitations and README).
2. POWER data has **latency** (recent days can be missing) — the code handles missing days and never interpolates.
3. **No weather forecast** anywhere: every indicator is computed from observed/historical data ("ریسک‌ها بر اساس داده تاریخی‌اند، نه پیش‌بینی").
4. The AI is **rule‑based keyword matching** — no LLM, no ML. Out‑of‑domain questions get an honest "I didn't understand" answer with suggestions.
5. Plant **diagnosis does not analyze images** (upload is stored as an observation only); symptom mapping is a conservative Persian keyword rule‑base that always refers to an expert. No pesticide doses are ever recommended.
6. **Prices/yields are user inputs** — the economics module never invents market prices ("قیمت ساختگی ارائه نمی‌شود").
7. Confidence is a **documented formula** (0.40·engine + 0.30·completeness + 0.20·freshness + 0.10·consistency), capped at 0.95 — not an ML probability.
8. GIBS layers are **visual context tiles** — the app explicitly labels TrueColor as "visual, not quantitative"; SMAP/MODIS product‑specific science (scale factors, QA bitmasks, reprojection) is not applied (README note #2).
9. Geospatial readers (HDF5/NetCDF/GeoTIFF) are **optional dependencies**; without them inspection returns 501 (and they are not installed in this environment).
10. Farmers must **enter soil data (FC/PWP/root depth) manually** for the full soil water balance; without it the irrigation advice says so and lowers confidence.
11. Single‑machine prototype: SQLite default, Django dev server for demos; production checklist (DEBUG=0, HTTPS, real WSGI server) is documented in README but **not configured by default**.
12. CMR download is **size‑limited** (`NASA_DOWNLOAD_MAX_MB`, default 100 MB) and domain‑restricted — it is not a bulk archive tool.

---

## F. Feature inventory (complete, from code — including items not in the slide deck)

| Feature | File / entry point | Status | Data used | Why it's special |
|---|---|---|---|---|
| Bilingual landing page (fa/en) | `core/templates/core/landing.html`, `core/static/core/auth.js` | Working (tested) | — | Full RTL/LTR switching |
| Account system for the whole platform (register/login/session, password hashing) | `farmer/views.py` `farmer_register/farmer_login`, `core/services/auth.py` `require_account` | Working (tested — `SessionAuthTests`) | — | Same account gates both the observatory and farmer app; 30‑day session |
| Earth dashboard: Leaflet map + coordinate picker | `core/static/core/app.js`, `core/templates/core/dashboard.html` | Working | Leaflet/OSM tiles | Click‑to‑set coordinates drives every analysis |
| NASA POWER time series + Chart.js + stats + provenance badge | `app.js loadPower/renderAnalysis`, `core/views.py power` | Working (live + tested) | NASA POWER | −999→null, provenance envelope, skeleton loading states |
| POWER parameter dictionary (10 curated params, bilingual) | `nasa.py PARAMETER_INFO`, `/api/power/parameters/` | Working | POWER metadata | Bilingual names/units |
| CMR catalog search + pagination (cursor deep‑paging) + granule search | `nasa.py search_collections/search_granules`, `app.js fetchCatalog/loadGranules` | Working (live + tested) | NASA CMR | CMR‑Search‑After cursor pagination |
| Granule download via app (streaming, allow‑list, size cap, bearer token) | `nasa.py download_nasa_file`, `/api/download/` | Working (tested with mocks) | Earthdata | Domain allow‑list + 100 MB cap |
| File inspection (CSV/JSON/GeoJSON/HDF5/NetCDF/GeoTIFF) | `nasa.py inspect_downloaded_file`, `/api/inspect/` | **Partial in this env** (CSV/JSON work; HDF5/NetCDF/GeoTIFF need optional deps → 501) | downloaded files | Structure + metadata report, no fabricated values |
| GIBS satellite layers (8 layers) + two‑date comparison + date/opacity control | `app.js SAT_LAYERS/setSatLayer/setSatLayer2` | Working (live tiles) | NASA GIBS WMTS | Client‑side only; honest "visual not quantitative" label; tile‑error handling |
| Climate Intelligence Engine: SPI/SPEI (1/3/6/12), anomalies, heatwave, frost, dry days, GDD, water balance + limitations metadata per indicator | `core/services/climate.py`, `/api/climate/` | Working (math unit‑tested) | NASA POWER (up to 5 years daily) | Pure‑Python statistics, no synthetic values |
| Agricultural Advisor (NASA POWER + FAOSTAT fusion, 9 crops, year‑over‑year) | `core/services/advice.py`, `/api/advice/` | Working | POWER + FAOSTAT | Cross‑source fusion with per‑item source tags |
| FAO Intelligence: Iran annual series + world ranking | `core/services/fao.py`, `/api/fao/*` | Working (live + tested) | FAOSTAT QCL | Dual API bases, 6 h cache, no synthetic fallback |
| Hybrid AI Agent (bilingual rule‑based intent router, fuzzy location) | `core/services/agent.py`, `agent_intents.py`, `/api/agent/` | Working (tested) | POWER/CMR/FAOSTAT via pipelines | Explainable answers with sources + limitations; asks instead of guessing |
| Bilingual searchable FAQ (17 entries) | `core/faq_data.py`, `/api/faq/` | Working | — | Covers POWER/SMAP/MODIS/CMR/quality flags |
| PDF climate report (Persian font) + analysis export CSV/PDF | `core/services/report.py`, `core/views.py export_analysis` | Working (tested) | Climate engine output | ReportLab Tahoma; full metadata in export |
| Scientific Workspace: save/list/delete/**reproduce** analyses; time series with baseline comparison | `core/views.py analysis_*`, `SavedAnalysis` model | Working (tested) | POWER/CMR | Reproducibility by stored parameters |
| Observability: `/api/health/` (deep check), `/api/metrics/` (requests, cache hit rate, DB latency, data freshness, tool calls) | `core/views.py`, `core/services/monitoring.py` | Working (tested) | internal | JSON structured logging (`core/logging.py`, `core/middleware.py` request IDs) |
| Data provenance infrastructure: DataContract envelope + validation + snapshots + ingestion log + data‑quality endpoint | `core/services/data_contract.py`, `provenance_store.py`, `core/models.py`, `/api/data-quality/` | Working (tested) | all external sources | Quality statuses valid/partial/stale/invalid |
| Data Integration Layer (SSRF guard, retry/backoff, rate limit, circuit breaker, cache, 25 MB cap) | `core/services/http.py` | Working (tested) | — | Single choke point for every external call |
| Inbound rate limiting (429 + Retry‑After) | `core/services/throttle.py` (decorators on expensive endpoints) | Working (tested) | — | Fixed window per IP per scope |
| Farmer onboarding: map‑based farm/field creation, soil profile, water sources | `farmer/views.py`, `farmer.js` | Working (tested) | Leaflet map + user input | Incremental field update API |
| Crop catalog (12 crops, FAO‑56 reference params) | `farmer/management/commands/seed_crops.py`, `/api/farmer/crops/` | Working (seeded live) | FAO‑56 reference values | Agronomic constants documented per crop |
| Crop recommendation ranking (climate fit + soil + salinity + water + season, score + reasons + confidence) | `farmer/services/recommend.py`, `/api/farmer/recommend/` | Working (tested) | POWER + CropProfile + field input | Every score item gives a written reason in Persian |
| Crop lifecycle calendar (GDD‑based stage, progress, harvest estimate; calendar fallback) | `farmer/services/lifecycle.py`, `/api/farmer/calendar/` | Working (tested) | POWER daily T2M | 6 generic FAO‑style stages; honest method/confidence |
| Irrigation Engine v2 (FAO‑56 PM ET₀ → ETc via Kc stage curve → effective rain → net need → TAW/RAW soil balance → volume scheduling by method efficiency) | `farmer/services/irrigation.py`, `et0.py`, `/api/farmer/irrigation/` | Working (tested + live) | POWER + SoilProfile + CropProfile | Never invents numbers; missing data lowers confidence and is listed |
| Daily command center («امروز در مزرعه چه کار کنم؟») | `farmer/services/daily.py`, `/api/farmer/daily/` | Working (tested + live) | all engines | Per‑field tasks + alerts + overdue/upcoming tasks |
| Farm tasks (create/list/done) | `farmer/views.py`, `/api/farmer/tasks/*` | Working (tested) | — | Tasks can be created by agent (source='agent') |
| Field observations with photo upload (validated, ≤5 MB, JPG/PNG/WebP) | `farmer/services/diagnosis.py save_observation`, `/api/farmer/observe/` | Working (tested) | uploaded image | PIL validation; stored as FarmObservation |
| Symptom diagnosis (rule‑based, conservative, expert referral) | `farmer/services/diagnosis.py`, `/api/farmer/diagnose/` | Working (tested) | text symptoms | Explicit "no ML image diagnosis" limitation |
| Farm economics (cost by category, cost/ha, revenue/profit scenarios ±30%, break‑even) | `farmer/services/economics.py`, `/api/farmer/economics/` | Working (tested) | FarmExpense + user yield/price | Never invents prices |
| Explainable Decision Engine (context completeness → engine recs → dedup/conflict → persist → feedback loop with outcome metrics) | `farmer/services/decision.py`, `/api/farmer/recommendations/*` | Working (tested) | irrigation/risk/lifecycle engines | Documented confidence formula; dedup; conflicts flagged |
| Risk alerts with lifecycle (fingerprint dedup, new/active/acknowledged/snoozed/resolved/expired, auto‑resolve when risk disappears) | `farmer/services/risk.py`, `farmer/models.py RiskAlert`, `/api/farmer/alerts/*` | Working (tested) | POWER → SPI/heatwave/frost/rain/water balance | Alert center with unread counts |
| Farmer Agent (intent → allow‑listed tool → simple/expert answer; mutating ops require explicit confirm) | `farmer/services/farmer_agent.py`, `tools.py`, `/api/farmer/agent/*` | Working (tested) | all farmer engines | Per‑farmer context cache; 409 confirmation preview flow |
| Tool registries with schema validation, permissions, output JSON‑validation, metrics | `core/services/tools.py`, `core/services/science_tools.py`, `farmer/services/tools.py` | Working (tested) | — | 15 farmer tools + 4 science tools registered |
| Simple/Expert mode, voice input (Web Speech), dark theme, offline indicator, bilingual UI (291 keys) | `farmer/static/farmer/*`, `core/static/core/*` | Working (browser‑dependent for voice) | — | Full fa/en i18n across both apps |
| DB backup/verify commands | `core/management/commands/db_backup.py`, `db_verify.py` | Working | DB | SQLite file backup or pg_dump |
| `/api/v1/` mirror | `config/urls.py` lines 79–82 | Working | — | All 67 API routes |

---

## G. FAO data — precise

Two **different** FAO sources are used; do not mix them on slides:

1. **FAO‑56 (method, not data):** the *Penman–Monteith reference evapotranspiration* methodology (Allen et al., 1998) implemented in `farmer/services/et0.py` and used as design basis in `farmer/services/irrigation.py` (Kc stage curve, TAW/RAW) and `core/services/advice.py` (crop profiles). It is a **computation method applied to NASA POWER weather data** — it fetches nothing from FAO.
2. **FAOSTAT (statistics data):** `core/services/fao.py` calls the FAOSTAT **API v1, domain `QCL`** (Production_Crops_Livestock) at `fenixservices.fao.org` / `faostatservices.fao.org`, for **Iran (area code 102)** with elements **2510 = production**, **2312 = area harvested**, **2413 = yield**, for **9 crops** (wheat 15, barley 44, rice paddy 27, maize 56, potatoes 116, tomatoes 388, sugar beet 157, + 2 more defined in `CROPS`). Units converted to tonnes/ha. **Cache: 6 hours (21600 s).** On failure it **raises** — no synthetic/demo data is ever substituted. Output shown to the user: e.g. *"Wheat annual production in Iran: X tonnes, area Y ha, yield Z t/ha"* (chart + table), and a **world ranking** for the same crop from the live all‑areas response (`fetch_world`).
3. **Fusion with NASA data:** yes — in `core/services/advice.py` (`get_advice`): NASA POWER 30‑day weather + FAOSTAT 5‑year yield trend are combined into one advisory payload with per‑item source tags, and SPI‑3/SPI‑6 drought context from 24 months of monthly POWER data.

---

## H. Project goal (from README + what the code actually does)

Iranian farmers and researchers lack a single trustworthy place where free NASA satellite/weather data becomes an actionable farm decision — most tools either show raw data or hide the provenance. This bilingual (Persian/English) Django platform unifies NASA POWER, CMR and GIBS with official FAOSTAT statistics under one honest data layer (every number carries source, quality and limitations) and turns it into concrete decisions: what to plant, how much to irrigate (FAO‑56 ET₀ with a confidence score), which risks threaten the field, and what to do today.

**Hero flow (fully working end‑to‑end in code):**
`/` landing → `/observatory/` place search (Nominatim) + NASA POWER live chart with provenance → register/login → `/farmer/` map‑based field creation → crop cycle → `/api/farmer/irrigation/` returns FAO‑56 Penman–Monteith ET₀ → ETc → net water need (mm) → daily volume (m³) with **confidence** and limitations → persisted as a Recommendation in `/api/farmer/recommendations/` → farmer accepts/feeds back. NASA data in, irrigation decision out, traceable at every step.

---

## I. Prioritization (Working features, scored 1–5)

| Feature | Impact | Creativity | Validity | Relevance | Presentation |
|---|---|---|---|---|---|
| Irrigation Engine (FAO‑56 PM ET₀ → net mm → m³, confidence) | 5 | 4 | 5 | 5 | 5 |
| Climate Intelligence Engine (SPI/SPEI/heatwave/frost/GDD) | 5 | 4 | 5 | 5 | 4 |
| Explainable Decision Engine + Risk Alert lifecycle (confidence + feedback) | 5 | 5 | 5 | 4 | 5 |
| Hybrid bilingual AI Agent (rule‑based, tool whitelist, confirm flow) | 4 | 5 | 4 | 4 | 5 |
| NASA+FAO fusion advisor & FAO world ranking | 4 | 4 | 5 | 4 | 4 |
| GIBS satellite layers + two‑date compare | 4 | 4 | 4 | 4 | 5 |
| POWER analysis workspace + provenance badge + reproduce/export | 3 | 4 | 5 | 4 | 4 |
| Provenance/Data‑Quality infrastructure (DataContract, snapshots, metrics) | 3 | 5 | 5 | 4 | 3 |
| Daily command center («what should I do today») | 5 | 4 | 4 | 5 | 5 |
| File download + inspection pipeline | 3 | 3 | 4 | 3 | 3 |

**Top 5 for the 7 slides:** 1) Irrigation recommendation with confidence (flagship: NASA data → mm of water), 2) Climate Intelligence Engine (scientific depth), 3) Explainable Decision Engine + risk alerts with feedback loop, 4) Bilingual AI agent over whitelisted tools, 5) NASA+FAOSTAT fusion / FAO ranking.
Corresponding screenshots: `feature_irrigation_confidence.png`, `feature_climate_engine.png`, `feature_decision_engine.png`, `feature_bilingual_agent.png`, `feature_nasa_fao_fusion.png`.

---

## Appendix — screenshot notes (for the slide maker)

- All screenshots were captured with **Playwright (Chromium), viewport 1600×900, deviceScaleFactor 2**, from the running server `http://127.0.0.1:8000`, **English UI** (language toggle).
- `04`–`06` and the farmer feature shots use a **sample demo account** (`demo@example.com`, farm "Demo Farm", field "Field 1", wheat cycle, sample expenses) created for the demo on 2026‑11‑14 — **this is sample data, not a real farm**. Live NASA/FAOSTAT values in the screenshots come from the real APIs at capture time.
