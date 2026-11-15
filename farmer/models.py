import secrets
from datetime import date

from django.db import models


def generate_api_key():
    return secrets.token_urlsafe(24)


class FarmerProfile(models.Model):
    """کشاورز — api_key برای سازگاری + login/password برای حساب واقعی."""
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20, blank=True)
    login = models.CharField(max_length=190, null=True, blank=True, unique=True,
                             help_text='email یا phone برای ورود با رمز')
    password_hash = models.CharField(max_length=128, blank=True)
    is_active = models.BooleanField(default=True)
    last_login = models.DateTimeField(null=True, blank=True)
    api_key = models.CharField(max_length=64, unique=True, db_index=True,
                               default=generate_api_key)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Farm(models.Model):
    farmer = models.ForeignKey(FarmerProfile, on_delete=models.CASCADE, related_name='farms')
    name = models.CharField(max_length=120)
    province = models.CharField(max_length=60, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.name} ({self.farmer.name})'


class Field(models.Model):
    """قطعه زمین — اطلاعات به‌تدریج دریافت می‌شود (همه فیلدها اختیاری)."""
    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name='fields')
    name = models.CharField(max_length=120)
    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)
    area_ha = models.FloatField(null=True, blank=True, help_text='هکتار')
    soil_type = models.CharField(max_length=60, blank=True,
                                 choices=[('', 'نامشخص'), ('clay', 'رسی'), ('loam', 'لوم'),
                                          ('sandy', 'شنی'), ('silty', 'سیلتی'), ('saline', 'شور')])
    salinity = models.CharField(max_length=30, blank=True,
                                choices=[('', 'نامشخص'), ('low', 'کم'), ('medium', 'متوسط'), ('high', 'زیاد')])
    water_source = models.CharField(max_length=60, blank=True,
                                    choices=[('', 'نامشخص'), ('well', 'چاه'), ('qanat', 'قنات'),
                                             ('river', 'رودخانه'), ('rainfed', 'دیم'), ('other', 'سایر')])
    irrigation_method = models.CharField(max_length=60, blank=True,
                                         choices=[('', 'نامشخص'), ('drip', 'قطره‌ای'), ('sprinkler', 'بارانی'),
                                                  ('flood', 'سطحی'), ('furrow', 'نوار'), ('rainfed', 'دیم')])
    slope = models.CharField(max_length=30, blank=True,
                             choices=[('', 'نامشخص'), ('flat', 'مسطح'), ('gentle', 'ملایم'), ('steep', 'شیب‌دار')])
    current_crop = models.ForeignKey('CropProfile', null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name='current_fields')
    planting_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.name} — {self.farm.name}'


class SoilProfile(models.Model):
    field = models.OneToOneField(Field, on_delete=models.CASCADE, related_name='soil')
    ph = models.FloatField(null=True, blank=True)
    organic_matter = models.FloatField(null=True, blank=True, help_text='درصد')
    field_capacity = models.FloatField(null=True, blank=True, help_text='FC — رطوبت ظرفیت مزرعه')
    wilting_point = models.FloatField(null=True, blank=True, help_text='PWP — نقطه پیwilting')
    root_depth_cm = models.FloatField(null=True, blank=True)
    notes = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class WaterSource(models.Model):
    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name='water_sources')
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=40, blank=True,
                            choices=[('', 'نامشخص'), ('well', 'چاه'), ('qanat', 'قنات'),
                                     ('river', 'رودخانه'), ('dam', 'سد'), ('other', 'سایر')])
    capacity_m3 = models.FloatField(null=True, blank=True)
    notes = models.TextField(blank=True)


class CropProfile(models.Model):
    """پروفایل محصول — پارامترهای زراعی برای موتورهای تصمیم."""
    key = models.CharField(max_length=40, unique=True)
    name_fa = models.CharField(max_length=80)
    name_en = models.CharField(max_length=80, blank=True)
    base_temp_c = models.FloatField(help_text='دمای پایه GDD')
    t_min_c = models.FloatField(null=True, blank=True, help_text='حداقل دمای مجاز')
    t_max_c = models.FloatField(null=True, blank=True, help_text='حداکثر دمای مجاز')
    gdd_total = models.FloatField(null=True, blank=True, help_text='مجموع GDD تا رسیدگی')
    water_need_mm = models.FloatField(null=True, blank=True, help_text='نیاز آبی کل دوره (mm)')
    kc_max = models.FloatField(default=1.0, help_text='ضریب گیاهی حداکثر (FAO-56)')
    growth_days = models.IntegerField(null=True, blank=True, help_text='طول دوره رشد (روز)')
    planting_seasons = models.JSONField(default=list, blank=True,
                                        help_text='فصل‌های کاشت: spring/autumn/winter')
    soil_preference = models.CharField(max_length=60, blank=True)
    salinity_tolerance = models.CharField(max_length=20, blank=True,
                                          choices=[('', 'نامشخص'), ('low', 'کم'), ('medium', 'متوسط'), ('high', 'زیاد')])
    notes = models.TextField(blank=True)

    def __str__(self):
        return self.name_fa


class CropCycle(models.Model):
    """چرخه کاشت یک محصول در یک قطعه — مبنای تقویم و دستیار روزانه."""
    field = models.ForeignKey(Field, on_delete=models.CASCADE, related_name='cycles')
    crop = models.ForeignKey(CropProfile, on_delete=models.CASCADE)
    planting_date = models.DateField()
    expected_harvest = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, default='active',
                              choices=[('active', 'فعال'), ('harvested', 'برداشت‌شده'), ('failed', 'ناموفق')])
    created_at = models.DateTimeField(auto_now_add=True)


class GrowthStage(models.Model):
    cycle = models.ForeignKey(CropCycle, on_delete=models.CASCADE, related_name='stages')
    name_fa = models.CharField(max_length=80)
    start_day = models.IntegerField(help_text='روز از کاشت')
    end_day = models.IntegerField(null=True, blank=True)
    tasks_fa = models.TextField(blank=True, help_text='کارهای این مرحله')
    risks_fa = models.TextField(blank=True, help_text='خطرات این مرحله')


class FarmObservation(models.Model):
    field = models.ForeignKey(Field, on_delete=models.CASCADE, related_name='observations')
    observed_at = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True)
    image = models.ImageField(upload_to='observations/', null=True, blank=True)


class IrrigationRecord(models.Model):
    field = models.ForeignKey(Field, on_delete=models.CASCADE, related_name='irrigations')
    date = models.DateField()
    amount_m3 = models.FloatField(null=True, blank=True)
    duration_min = models.IntegerField(null=True, blank=True)
    method = models.CharField(max_length=40, blank=True)
    notes = models.TextField(blank=True)


class FertilizerRecord(models.Model):
    field = models.ForeignKey(Field, on_delete=models.CASCADE, related_name='fertilizers')
    date = models.DateField()
    kind = models.CharField(max_length=80, blank=True)
    amount_kg = models.FloatField(null=True, blank=True)
    notes = models.TextField(blank=True)


class FarmTask(models.Model):
    field = models.ForeignKey(Field, on_delete=models.CASCADE, related_name='tasks', null=True, blank=True)
    farmer = models.ForeignKey(FarmerProfile, on_delete=models.CASCADE, related_name='tasks')
    title = models.CharField(max_length=160)
    due_date = models.DateField(null=True, blank=True)
    done = models.BooleanField(default=False)
    done_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=40, blank=True,
                              help_text='manual / engine / agent')
    created_at = models.DateTimeField(auto_now_add=True)


class RiskAlert(models.Model):
    field = models.ForeignKey(Field, on_delete=models.CASCADE, related_name='alerts', null=True, blank=True)
    farmer = models.ForeignKey(FarmerProfile, on_delete=models.CASCADE, related_name='alerts')
    kind = models.CharField(max_length=40)
    severity = models.CharField(max_length=20, default='medium',
                                choices=[('low', 'کم'), ('medium', 'متوسط'), ('high', 'زیاد'), ('critical', 'بحرانی')])
    title_fa = models.CharField(max_length=160)
    detail_fa = models.TextField(blank=True)
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    source = models.CharField(max_length=60, blank=True, help_text='NASA POWER / GIBS / FAO / engine')
    is_read = models.BooleanField(default=False)
    dismissed = models.BooleanField(default=False)
    # Phase 4 — Alert lifecycle
    status = models.CharField(max_length=20, default='new',
                              choices=[('new', 'جدید'), ('active', 'فعال'),
                                       ('acknowledged', 'دیده‌شده'), ('snoozed', 'به تعویق افتاده'),
                                       ('resolved', 'حل‌شده'), ('expired', 'منقضی')])
    fingerprint = models.CharField(max_length=64, blank=True, db_index=True,
                                   help_text='hash(field+kind) برای dedup')
    evidence = models.JSONField(default=list, blank=True)
    expires_at = models.DateField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Recommendation(models.Model):
    """توصیه تصمیم‌گیر — ساختار کامل طبق spec."""
    farmer = models.ForeignKey(FarmerProfile, on_delete=models.CASCADE, related_name='recommendations')
    field = models.ForeignKey(Field, on_delete=models.CASCADE, related_name='recommendations', null=True, blank=True)
    title_fa = models.CharField(max_length=160)
    action_fa = models.TextField(blank=True, help_text='اقدام پیشنهادی')
    timing_fa = models.CharField(max_length=120, blank=True, help_text='زمان انجام')
    reason_fa = models.TextField(blank=True, help_text='دلیل توصیه')
    importance = models.CharField(max_length=20, default='medium',
                                  choices=[('low', 'کم'), ('medium', 'متوسط'), ('high', 'زیاد')])
    confidence = models.FloatField(null=True, blank=True, help_text='۰ تا ۱')
    data_sources = models.JSONField(default=list, blank=True)
    data_date = models.DateField(null=True, blank=True, help_text='تاریخ داده مبنا')
    limitations_fa = models.TextField(blank=True)
    # Phase 2 — Explainable Decision Intelligence
    status = models.CharField(max_length=20, default='new',
                              choices=[('new', 'جدید'), ('accepted', 'پذیرفته'),
                                       ('rejected', 'رد شده'), ('completed', 'انجام شده'),
                                       ('ignored', 'نادیده گرفته')])
    valid_until = models.DateField(null=True, blank=True, help_text='تاریخ انقضای توصیه')
    review_at = models.DateField(null=True, blank=True, help_text='زمان بازبینی')
    evidence = models.JSONField(default=list, blank=True, help_text='شواهد پشتیبان')
    expected_benefit = models.CharField(max_length=200, blank=True)
    estimated_cost = models.CharField(max_length=120, blank=True, help_text='هزینه تخمینی اقدام')
    required_resources = models.JSONField(default=list, blank=True, help_text='منابع لازم')
    outcome_note = models.TextField(blank=True, help_text='مشاهده نتیجه پس از اجرا')
    outcome_metrics = models.JSONField(default=dict, blank=True,
                                       help_text='نتیجه کمی: yield/cost/water/rating')
    outcome_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class HarvestRecord(models.Model):
    cycle = models.ForeignKey(CropCycle, on_delete=models.CASCADE, related_name='harvests')
    date = models.DateField()
    yield_kg = models.FloatField(null=True, blank=True)
    quality = models.CharField(max_length=40, blank=True)
    notes = models.TextField(blank=True)


class FarmExpense(models.Model):
    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name='expenses')
    date = models.DateField(default=date.today)
    category = models.CharField(max_length=40,
                                choices=[('seed', 'بذر'), ('land', 'آماده‌سازی'), ('water', 'آب'),
                                         ('fertilizer', 'کود'), ('pesticide', 'سم'), ('labor', 'نیروی کار'),
                                         ('harvest', 'برداشت'), ('transport', 'حمل‌ونقل'), ('other', 'سایر')])
    amount = models.FloatField(help_text='مبلغ (واحد پول کاربر)')
    currency = models.CharField(max_length=10, default='IRT')
    notes = models.TextField(blank=True)
