"""Shared intent resolver for controlled agents (Phase 6).

Rule-based, bilingual, deterministic. The resolver only classifies the
user's goal; all numeric work stays inside specialist engines/tools.
"""
import re

CANONICAL_INTENTS = [
    'weather_query', 'irrigation_question', 'crop_advice', 'risk_analysis',
    'economic_analysis', 'farm_operation', 'scientific_research',
    'satellite_search', 'general_question',
]

_KEYWORDS = {
    'weather_query': [
        'weather', 'forecast', 'temperature', 'rain', 'precipitation', 'humidity',
        'هوا', 'آب‌وهوا', 'هواشناسی', 'پیش‌بینی', 'دما', 'باران', 'بارش', 'رطوبت',
    ],
    'irrigation_question': [
        'irrigation', 'water need', 'water requirement', 'sprinkler', 'drip',
        'آبیاری', 'نیاز آبی', 'آب مورد نیاز', 'آب', 'قطره‌ای', 'بارانی',
    ],
    'crop_advice': [
        'what crop', 'which crop', 'crop recommendation', 'planting', 'sow',
        'چه محصول', 'کدام محصول', 'محصول مناسب', 'چی بکارم', 'کاشت', 'بکارم',
        'توصیه محصول', 'محصول',
    ],
    'risk_analysis': [
        'risk', 'warning', 'alert', 'drought', 'frost', 'heat stress', 'danger',
        'خطر', 'هشدار', 'ریسک', 'خشکسالی', 'سرما', 'یخبندان', 'گرما', 'تنش گرمایی',
    ],
    'economic_analysis': [
        'economics', 'cost', 'profit', 'revenue', 'expense', 'price', 'budget',
        'اقتصاد', 'هزینه', 'سود', 'درآمد', 'قیمت', 'بودجه', 'هزینه‌ها',
    ],
    'farm_operation': [
        'record', 'log', 'save', 'create task', 'new task', 'observation', 'note',
        'ثبت', 'ثبت کن', 'یادداشت', 'مشاهده', 'کار جدید', 'وظیفه', 'عملیات',
    ],
    'scientific_research': [
        'research', 'study', 'dataset', 'data source', 'methodology', 'science',
        'analysis', 'indicator', 'climate', 'environment',
        'پژوهش', 'تحقیق', 'داده', 'منبع داده', 'روش‌شناسی', 'علمی', 'تحلیل', 'شاخص', 'اقلیم', 'محیط',
    ],
    'satellite_search': [
        'satellite', 'imagery', 'remote sensing', 'catalog', 'collection', 'granule', 'map layer', 'search data',
        'ماهواره', 'سنجش از دور', 'کاتالوگ', 'مجموعه داده', 'گرانول', 'لایه نقشه', 'جستجوی داده', 'تصویر ماهواره‌ای',
    ],
    'general_question': ['hello', 'hi', 'help', 'سلام', 'درود', 'کمک', 'چیست', 'how'],
}

_OPERATION_VERBS = re.compile(
    r'(ثبت|ثبت کن|save|record|log|add|create|new|یادداشت|مشاهده|کار جدید|وظیفه)', re.I)


def resolve_intent(text):
    """Return {'intent', 'confidence', 'matched'} for canonical intents."""
    q = (text or '').strip().lower()
    if not q:
        return {'intent': 'general_question', 'confidence': 0.0, 'matched': []}

    scores = {}
    matched = {}
    for intent, keywords in _KEYWORDS.items():
        hits = [k for k in keywords if k in q]
        if hits:
            # operation verbs are stronger evidence for farm_operation
            weight = 2 if intent == 'farm_operation' and _OPERATION_VERBS.search(q) else 1
            scores[intent] = len(hits) * weight
            matched[intent] = hits[:5]

    if not scores:
        return {'intent': 'general_question', 'confidence': 0.0, 'matched': []}

    best = max(scores, key=scores.get)
    # Prefer explicit operation verbs for mutating intents.
    if best != 'farm_operation' and scores.get('farm_operation') and _OPERATION_VERBS.search(q):
        best = 'farm_operation'
    total = sum(scores.values())
    return {'intent': best, 'confidence': round(scores[best] / total, 2),
            'matched': matched.get(best, [])}


def canonical_to_legacy(intent):
    """Map canonical intents to existing farmer-agent engine names."""
    return {
        'weather_query': 'weather',
        'irrigation_question': 'irrigation',
        'crop_advice': 'crop_advice',
        'risk_analysis': 'risk',
        'economic_analysis': 'economics',
        'farm_operation': 'farm_operation',
        'scientific_research': 'scientific_research',
        'satellite_search': 'satellite_search',
        'general_question': None,
    }.get(intent)
