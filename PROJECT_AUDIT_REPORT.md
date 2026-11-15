# PROJECT AUDIT REPORT — Phase 0
**NASA Earth Intelligence & Farmer Assistant**
تاریخ: ۲۰۲۶-۱۱-۱۳ · وضعیت: Read-only audit — بدون تغییر سورس

---

## ۱. معماری واقعی

### ساختار پروژه

```
nasa_unified/
├── config/          settings, urls, wsgi/asgi — بدون auth middleware، بدون sessions app
├── core/            Earth Intelligence (scientific)
│   ├── views.py     ۱۵ endpoint
│   ├── services/    nasa, climate, fao, agent, advice, geocode, report, http, throttle
│   ├── faq_data.py  دانشنامه static
│   └── templates/core/dashboard.html  (~۵۵۰ خط readable)
├── farmer/          Farmer Assistant
│   ├── models.py    ۱۵ مدل
│   ├── views.py     ۲۴ endpoint
│   ├── services/    recommend, lifecycle, irrigation, risk, economics, daily, farmer_agent, diagnosis
│   └── templates/farmer/dashboard.html
└── shared/          tokens.css + i18n/{fa,en}.json (static only — نه Django app)
```

### وابستگی بین دو محصول
- **صفر وابستگی مستقیم**: farmer از core import نمی‌کند؛ فقط `shared/tokens.css` و `shared/i18n` مشترک است.
- farmer از NASA POWER به‌صورت **مستقیم** استفاده نمی‌کند — از طریق موتورهای داخلی (irrigation/risk) که خودشان NASA را صدا می‌زنند؟ **خیر** — موتورهای farmer فعلاً rule-based + داده‌های DB هستند؛ اتصال مستقیم به `core.services.nasa` وجود ندارد. این یعنی Farmer Assistant مستقل ولی **بدون داده اقلیمی زنده** در برخی بخش‌ها (risk از SPI استفاده می‌کند؟ — بررسی شد: `risk.py` به climate متصل نیست، rule-based است).

### Middleware
فقط Security + Common + CSRF. **بدون AuthenticationMiddleware** — farmer از `X-Farmer-Key` header + `require_farmer` decorator استفاده می‌کند؛ core کاملاً public است.

### External Integrations
| منبع | ماژول | پروتکل |
|---|---|---|
| NASA POWER | `core/services/nasa.py` | REST JSON |
| NASA CMR | `core/services/nasa.py` | REST JSON |
| NASA GIBS | frontend tile layer | WMTS/XYZ tiles |
| FAOSTAT | `core/services/fao.py` | REST JSON |
| Nominatim | `core/services/geocode.py` | REST |
| Open-Meteo | `core/services/http.py` allowlist | REST (آماده، استفاده؟) |

همه از `core/services/http.py` عبور می‌کنند: timeout، retry/backoff، rate-limit، cache، **SSRF guard (https + host whitelist)**، سقف ۲۵MB.

---

## ۲. Database

### مدل‌ها (۱۵) و روابط
| مدل | FK/Relation | Index |
|---|---|---|
| FarmerProfile | — | api_key db_index ✅ |
| Farm | →FarmerProfile CASCADE | ❌ |
| Field | →Farm CASCADE, →CropProfile SET_NULL | ❌ |
| SoilProfile | OneToOne→Field | ❌ |
| WaterSource | →Farm CASCADE | ❌ |
| CropProfile | — (seeded) | ❌ |
| CropCycle | →Field, →CropProfile | ❌ |
| GrowthStage | →CropCycle | ❌ |
| FarmObservation | →Field | ❌ |
| IrrigationRecord | →Field | ❌ |
| FertilizerRecord | →Field | ❌ |
| FarmTask | →Field(null), →FarmerProfile | ❌ |
| RiskAlert | →Field(null), →FarmerProfile | ❌ |
| Recommendation | →FarmerProfile, →Field(null) | ❌ |
| HarvestRecord | →CropCycle | ❌ |
| FarmExpense | →Farm | ❌ |

### یافته‌ها
- ✅ **مالکیت**: `get_owned_field`/`get_owned_farm` در services — همه queryها با `farm__farmer=farmer` فیلتر می‌شوند. جداسازی کاربران درست است.
- ⚠️ **Index**: فقط `api_key` ایندکس دارد؛ FKها بدون `db_index` صریح (Django به‌صورت خودکار index روی FK می‌سازد — پس OK، ولی `Meta.indexes` برای کوئری‌های پرتکرار مثل `Field.objects.filter(farm__farmer=...)` مفید است).
- ⚠️ **RiskAlert و Recommendation**: مدل‌ها وجود دارند ولی `risk.py` و `recommend.py` **آن‌ها را persist نمی‌کنند** — محاسبات on-the-fly هستند. مدل‌ها برای آینده (notification center) آماده‌اند.
- ❌ **Snapshot/Provenance**: هیچ مدل snapshot یا data-provenance وجود ندارد — نتایج NASA/FAO cache می‌شوند (Django cache) ولی در DB ذخیره نمی‌شوند.
- ✅ Migrationها sync هستند (`makemigrations --check` → No changes).

### Migrationهای آینده لازم
- `RiskAlert.is_read/dismissed` + `notified_at` (notification center)
- `Recommendation.status` (accepted/dismissed)
- `DataSnapshot` (اختیاری — provenance)
- Indexهای composite روی `(farm__farmer, date)` برای records

---

## ۳. کیفیت داده

| منبع | نوع | واحد | تناوب | اعتبارسنجی | Cache | Failure |
|---|---|---|---|---|---|---|
| NASA POWER | meteorological | °C, mm, MJ/m², kWh/m²/day | daily/hourly | schema check در nasa.py | Django cache | DataSourceError → JSON error |
| NASA CMR | metadata catalog | — | — | JSON parse | cache | error JSON |
| NASA GIBS | imagery tiles | — | 8/16-day | tile error count | browser/CDN | tileerror counter + status msg |
| FAOSTAT | agricultural stats | tonnes, ha, kg/ha | annual | QCL validation | cache | honest error, no fake data |
| Nominatim | geocoding | lat/lon | — | — | cache | error |

- ✅ `fetched_at` در پاسخ climate برگردانده و در UI نمایش داده می‌شود.
- ✅ `limitations` صریح در خروجی‌های علمی.
- ⚠️ Farmer engines (irrigation/risk) **داده زنده NASA نمی‌گیرند** — rule-based روی داده‌های DB؛ در UI به‌عنوان «توصیه rule-based» اعلام شده (good honesty).

---

## ۴. موتورهای کشاورزی

| موتور | خطوط | ورودی | خروجی | وابستگی | ریسک |
|---|---|---|---|---|---|
| recommend | ۱۳۷ | Field+soil+climate params | ranking محصولات + reasons_fa | CropProfile | ✅ محدودیت‌ها اعلام می‌شود |
| lifecycle | ۱۱۰ | CropCycle+GDD | stage فعلی + tasks | CropProfile.gdd_total | ⚠️ بدون داده آب‌وهوا واقعی GDD تقریبی |
| irrigation | ۹۵ | Field+soil+PET? | نیاز آبی + توصیه | SoilProfile | ⚠️ rule-based، بدون داده بارش زنده |
| risk | ۸۵ | Field+alerts | لیست ریسک | — | ⚠️ persist نمی‌کند |
| economics | ۵۸ | Farm+expenses+yield+price | cost/profit/breakeven | FarmExpense | ✅ user-provided prices |
| daily | ۱۰۳ | همه fieldها | briefing تجمیعی | lifecycle+irrigation+risk | ✅ generated_at دارد |
| farmer_agent | ۱۳۴ | question+field_id | intent→engine→answer_fa | همه موتورهای بالا | ✅ Agent محاسبه نمی‌کند — engineها را صدا می‌زند |

**نکته مثبت**: `farmer_agent` مستقیماً محاسبه نمی‌کند — intent detect → engine call → simple answer. مطابق قانون ۱۱ master instructions.

**محاسبات بدون داده کافی**: lifecycle GDD بدون داده دمای زنده → تخمین؛ irrigation بدون بارش واقعی → نیاز خالص. هر دو در `limitations` اعلام می‌شوند.

---

## ۵. Frontend

### Earth Intelligence `/`
- ✅ ۸ تب، readable HTML (۵۵۰ خط)، i18n متمرکز (۴۹ کلید fa/en)
- ✅ Satellite: ۸ لایه GIBS + opacity + legend + desc_fa
- ✅ Climate: SPI/SPEI/GDD + PDF/CSV + methodology details
- ✅ Accessibility: skip-link, aria-live, focus-visible
- ⚠️ i18n ناقص — بیشتر متن‌ها hardcoded فارسی در HTML/JS
- ⚠️ Satellite compare (satMapB) basic

### Farmer Assistant `/farmer/`
- ✅ Onboarding ۲مرحله‌ای + نقشه Leaflet
- ✅ Today command center + action cards + quick actions
- ✅ Simple/Expert mode + offline banner + voice input
- ✅ Agent field-aware + suggested questions
- ✅ Operations API (irrigation/fertilizer/observation)
- ⚠️ Notification center ندارد (RiskAlert persist نمی‌شود)
- ⚠️ Image upload فقط observation note — بدون diagnosis واقعی

---

## ۶. تست‌ها

**۷۲/۷۲ سبز** (۲۳.۴ ثانیه) — `python manage.py test`

| دسته | تعداد | وضعیت |
|---|---|---|
| Unit (services) | ~۲۰ | ✅ |
| API Contract | ~۳۰ | ✅ |
| Integration | ~۱۵ | ✅ |
| Regression | ~۷ | ✅ |
| Frontend | ۰ | ❌ هیچ تست JS/browser |
| Security | ~۵ | ✅ (auth, ownership) |

---

## ۷. مشکلات قطعی

1. **RiskAlert/Recommendation persist نمی‌شوند** — مدل‌ها بلااستفاده
2. **Farmer engines بدون داده اقلیمی زنده** — irrigation/risk rule-based
3. **i18n ناقص** — ۴۹ کلید در برابر صدها متن hardcoded
4. **بدون frontend tests** — هیچ JS test یا browser test
5. **بدون session auth** — api_key در localStorage (XSS risk)
6. **بدون rate limiting روی farmer APIs** — فقط core http.py throttle دارد
7. **SoilProfile/WaterSource بدون UI** — مدل‌ها هستند ولی farmer.js فرم ندارد

## ۸. ریسک‌های معماری

- SQLite برای production (single-file، concurrent writes)
- `shared/` static-only — نه Django app، نه reusable Python
- farmer_agent از `globals()` استفاده نمی‌کند (fix شد) ولی context passing ساده است
- بدون Celery/background tasks — NASA calls synchronous (timeout risk)
- بدون API versioning (`/api/` بدون v1)

## ۹. بدهی فنی (Technical Debt)

| اولویت | مورد |
|---|---|
| P0 | Persist RiskAlert + notification center |
| P0 | Frontend tests (حداقل smoke) |
| P1 | i18n کامل |
| P1 | Farmer engines → NASA data integration |
| P1 | Rate limiting farmer APIs |
| P2 | API versioning |
| P2 | PostgreSQL migration path |
| P2 | SoilProfile/WaterSource UI |

## ۱۰. اولویت‌بندی

- **P0**: Notification center (RiskAlert persist + is_read) — آخرین بدهی بزرگ farmer
- **P0**: Frontend smoke tests
- **P1**: i18n کامل + farmer engines data integration
- **P1**: Rate limiting + API versioning
- **P2**: PostgreSQL + background tasks + SoilProfile UI

## ۱۱. برنامه مراحل بعدی

1. **Phase 1**: Notification Center — RiskAlert.is_read/dismissed + endpoints + UI badge
2. **Phase 2**: Farmer engines → NASA POWER integration (irrigation real PET)
3. **Phase 3**: i18n کامل + frontend smoke tests
4. **Phase 4**: Rate limiting + API versioning + PostgreSQL path

---
*Audit completed — no source code modified.*
