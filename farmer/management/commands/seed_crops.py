"""Seed CropProfile catalog with agronomic parameters for Iranian crops.

Values are standard FAO-56 / extension-service references (approximate,
documented per crop). Run: python manage.py seed_crops
"""
from django.core.management.base import BaseCommand

from farmer.models import CropProfile

# key, name_fa, name_en, base_temp, t_min, t_max, gdd_total, water_need_mm,
# kc_max, growth_days, seasons, soil_pref, salinity_tol, notes
CROPS = [
    ('wheat', 'گندم', 'Wheat', 0, -5, 35, 1800, 450, 1.15, 150, ['winter', 'spring'], 'loam', 'medium',
     'گندم بهمن/اسفند یا فروردین؛ نیاز آبی متوسط؛ حساس به سرما در مرحله گل‌دهی'),
    ('barley', 'جو', 'Barley', 0, -6, 36, 1700, 400, 1.1, 140, ['winter', 'spring'], 'loam', 'medium',
     'جو نسبت به گندم سرما و خشکی را بهتر تحمل می‌کند'),
    ('rice', 'برنج', 'Rice', 10, 12, 40, 1800, 1200, 1.2, 140, ['spring'], 'clay', 'low',
     'برنج نیاز آبی بسیار بالا؛ فقط در اراضی شالی‌زاری با آب فراوان'),
    ('maize', 'ذرت دانه‌ای', 'Maize', 8, 10, 42, 1600, 600, 1.2, 130, ['spring', 'summer'], 'loam', 'low',
     'ذرت به گرما و نور زیاد نیاز دارد؛ حساس به سرما'),
    ('potato', 'سیب‌زمینی', 'Potato', 7, 5, 30, 1400, 500, 1.15, 110, ['winter', 'spring'], 'sandy', 'low',
     'سیب‌زمینی خاک شنی خوب با زهکشی؛ حساس به شوری و گرمای شدید'),
    ('tomato', 'گوجه‌فرنگی', 'Tomato', 10, 8, 35, 1200, 550, 1.15, 110, ['spring', 'summer'], 'loam', 'medium',
     'گوجه‌فرنگی در گلخانه یا فضای باز؛ نیاز آبی یکنواخت'),
    ('sugarbeet', 'چغندرقند', 'Sugar beet', 0, -3, 32, 1600, 550, 1.1, 180, ['spring'], 'loam', 'medium',
     'چغندرقند دوره رشد بلند؛ مناسب مناطق سرد و نیمه‌خشک'),
    ('dates', 'خرما', 'Dates', 18, 10, 45, 2200, 900, 1.0, 240, ['perennial'], 'sandy', 'high',
     'خرما درخت چندساله؛ نیاز آبی بالا اما شوری را تحمل می‌کند'),
    ('pistachio', 'پسته', 'Pistachio', 10, 5, 40, 2000, 700, 0.9, 240, ['perennial'], 'loam', 'medium',
     'پسته درخت چندساله؛ مناسب مناطق گرم و خشک با زمستان سرد'),
    ('sunflower', 'آفتابگردان', 'Sunflower', 8, 5, 40, 1400, 500, 1.15, 110, ['spring', 'summer'], 'loam', 'low',
     'آفتابگردان به نور و گرما نیاز دارد؛ مناسب کشت دانه'),
    ('saffron', 'زعفران', 'Saffron', 5, -5, 30, 1200, 350, 0.8, 180, ['autumn'], 'loam', 'medium',
     'زعفران پیازچه در پاییز؛ نیاز آبی کم؛ مناسب مناطق نیمه‌خشک'),
    ('cotton', 'پنبه', 'Cotton', 15, 10, 40, 1600, 700, 1.15, 160, ['spring'], 'loam', 'medium',
     'پنبه نیاز آبی و گرمایی بالا؛ مناسب مناطق گرم'),
]


class Command(BaseCommand):
    help = 'Seed CropProfile catalog with agronomic parameters'

    def handle(self, *args, **options):
        created = updated = 0
        for (key, name_fa, name_en, base, tmin, tmax, gdd, water, kc, days,
             seasons, soil, sal, notes) in CROPS:
            obj, was_created = CropProfile.objects.update_or_create(
                key=key,
                defaults=dict(name_fa=name_fa, name_en=name_en, base_temp_c=base,
                              t_min_c=tmin, t_max_c=tmax, gdd_total=gdd,
                              water_need_mm=water, kc_max=kc, growth_days=days,
                              planting_seasons=seasons, soil_preference=soil,
                              salinity_tolerance=sal, notes=notes))
            created += was_created
            updated += not was_created
        self.stdout.write(self.style.SUCCESS(
            f'Crops seeded: {created} created, {updated} updated, total {CropProfile.objects.count()}'))
