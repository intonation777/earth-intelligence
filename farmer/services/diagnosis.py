"""Plant Problem Diagnosis — conservative, rule-based.

No ML model is connected: the engine does NOT claim to diagnose from
image pixels. It (1) validates and stores the uploaded image as a
FarmObservation, (2) maps user-described symptoms to possible causes
with safe first actions, and (3) always refers uncertain cases to an
agricultural expert. No pesticide doses are ever recommended.
"""
import os
from datetime import date

from django.core.files.storage import default_storage
from PIL import Image

from ..models import FarmObservation, Field

MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_EXT = {'.jpg', '.jpeg', '.png', '.webp'}

# symptom keyword → possible causes + safe actions (conservative)
SYMPTOM_MAP = {
    'زردی': {'causes': ['کمبود نیتروژن', 'کمبود آهن', 'آبیاری زیاد/کم', 'بیماری ریشه'],
             'actions': ['برگ‌های زرد را عکس بگیرید', 'آبیاری را بررسی کنید', 'با کارشناس خاک مشورت کنید']},
    'لکه': {'causes': ['بیماری قارچی', 'آفت', 'آسیب مکانیکی', 'کمبود عناصر'],
            'actions': ['لکه‌ها را از نزدیک عکس بگیرید', 'رطوبت برگ را بررسی کنید', 'با کارشناس گیاه‌پزشکی مشورت کنید']},
    'پیچیدگی': {'causes': ['آفت (شپشک/کنه)', 'ویروس', 'کمبود عناصر', 'علف‌کش'],
                'actions': ['برگ‌های پیچیده را بررسی کنید', 'سم‌پاشی خودسرانه نکنید', 'نمونه به آزمایشگاه ببرید']},
    'پوسیدگی': {'causes': ['بیماری قارچی', 'آبیاری زیاد', 'زخم باکتریایی'],
                'actions': ['قسمت پوسیده را خشک نگه دارید', 'ابزار را ضدعفونی کنید', 'با کارشناس مشورت کنید']},
    'آفت': {'causes': ['حشرات مکنده', 'لارو', 'کنه'],
            'actions': ['آفت را شناسایی کنید', 'سم‌پاشی فقط با نسخه کارشناس', 'دوران‌های آفت را یادداشت کنید']},
    'خشک': {'causes': ['کم‌آبی', 'تنش گرمایی', 'آسیب ریشه', 'شوری'],
            'actions': ['رطوبت خاک را بررسی کنید', 'آبیاری را تنظیم کنید', 'شوری خاک را آزمایش کنید']},
    'لکه قهوه‌ای': {'causes': ['بیماری قارچی', 'سوختگی آفتاب', 'آسیب سرما'],
                    'actions': ['محل لکه را مشخص کنید', 'رطوبت را کاهش دهید', 'با کارشناس مشورت کنید']},
    'ریزش': {'causes': ['تنش آبی', 'بیماری', 'آفت', 'کمبود عناصر'],
             'actions': ['علت را بررسی کنید', 'آبیاری و تغذیه را پایش کنید', 'نمونه به آزمایشگاه ببرید']},
    'لکه سفید': {'causes': ['بیماری قارچی (سفیدک)', 'آفت', 'کمبود عناصر'],
                 'actions': ['سطح زیر برگ را بررسی کنید', 'رطوبت را کاهش دهید', 'با کارشناس مشورت کنید']},
    'لکه سیاه': {'causes': ['بیماری قارچی', 'آسیب سرما', 'آفتاب‌سوختگی'],
                  'actions': ['محل لکه را مشخص کنید', 'برگ‌های شدید را حذف کنید', 'با کارشناس مشورت کنید']},
}


def validate_image(upload):
    """Validate uploaded image: extension, size, PIL-decodable."""
    name = getattr(upload, 'name', '')
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED_EXT:
        return None, 'فرمت تصویر نامعتبر — فقط JPG/PNG/WebP'
    if upload.size > MAX_IMAGE_BYTES:
        return None, 'حجم تصویر بیش از ۵ مگابایت است'
    try:
        img = Image.open(upload)
        img.verify()
        upload.seek(0)
    except Exception:
        return None, 'فایل تصویر معتبر نیست'
    return ext, None


def save_observation(field, upload, note=''):
    """Store image as FarmObservation. Returns (observation, error)."""
    ext, err = validate_image(upload)
    if err:
        return None, err
    path = default_storage.save(f'observations/{field.id}/{date.today().isoformat()}_{upload.name}', upload)
    obs = FarmObservation.objects.create(field=field, note=note, image=path)
    return obs, None


def diagnose(symptoms, crop_name=None, stage=None):
    """Map symptoms → possible causes + safe actions. Conservative."""
    symptoms = [s.strip() for s in (symptoms or []) if s and s.strip()]
    if not symptoms:
        return {'error': 'علائم را توصیف کنید (مثلاً زردی برگ، لکه قهوه‌ای)'}

    matched = []
    all_causes = {}
    for s in symptoms:
        key = next((k for k in SYMPTOM_MAP if k in s), None)
        if key:
            entry = SYMPTOM_MAP[key]
            matched.append({'symptom': s, 'key': key,
                            'causes': entry['causes'], 'actions': entry['actions']})
            for c in entry['causes']:
                all_causes[c] = all_causes.get(c, 0) + 1

    if not matched:
        return {
            'matched': [], 'possible_causes': [],
            'advice_fa': 'علائم توصیف‌شده در پایگاه ما نیست. لطفاً عکس واضح از برگ/ساقه/میوه بگیرید و با کارشناس گیاه‌پزشکی مشورت کنید.',
            'limitations_fa': ['تشخیص خودکار تصویر بدون مدل ML انجام نمی‌شود — فقط علائم متنی تحلیل می‌شوند.'],
            'expert_referral': True,
        }

    # rank causes by frequency across symptoms
    ranked = sorted(all_causes.items(), key=lambda x: -x[1])
    safe_actions = []
    for m in matched:
        safe_actions.extend(m['actions'])
    # dedupe preserve order
    seen = set(); safe_actions = [a for a in safe_actions if not (a in seen or seen.add(a))]

    return {
        'matched': matched,
        'possible_causes': [{'cause': c, 'score': n} for c, n in ranked],
        'safe_actions_fa': safe_actions[:6],
        'advice_fa': f"{len(matched)} علامت شناسایی شد. {len(ranked)} علت محتمل — قبل از هر سم‌پاشی با کارشناس گیاه‌پزشکی مشورت کنید.",
        'limitations_fa': [
            'این تحلیل rule-based بر اساس علائم متنی است، نه تشخیص تصویری ML.',
            'دوز سم، نوع سم و زمان سم‌پاشی فقط با نسخه کارشناس گیاه‌پزشکی تعیین شود.',
            'در موارد نامطمئن، نمونه به آزمایشگاه گیاه‌پزشکی ببرید.',
        ],
        'expert_referral': True,
        'crop': crop_name, 'stage': stage,
    }
