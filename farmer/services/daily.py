"""Daily Farmer Assistant — «امروز در مزرعه چه کار کنم؟»

Aggregates per-field: lifecycle stage tasks, irrigation need, harvest
proximity, weather warnings (SPI/heatwave via Climate Engine, cached),
overdue tasks and active risk alerts. Every item carries source and
honest limitations.
"""
from datetime import date, timedelta, datetime

from ..models import Field, FarmTask, RiskAlert, CropCycle
from .lifecycle import get_lifecycle
from .irrigation import get_irrigation_advice


def get_daily_briefing(farmer):
    today = date.today()
    fields = Field.objects.filter(farm__farmer=farmer).select_related('farm', 'current_crop')
    items = []

    for field in fields:
        entry = {'field_id': field.id, 'field_name': field.name,
                 'farm_name': field.farm.name, 'tasks': [], 'alerts': []}

        # --- active cycle → stage tasks + harvest proximity ---
        cycle = (CropCycle.objects.filter(field=field, status='active')
                 .select_related('crop').order_by('-planting_date').first())
        if cycle:
            try:
                life = get_lifecycle(cycle)
                stage = life.get('current_stage') or {}
                if stage.get('tasks_fa'):
                    entry['tasks'].append({
                        'kind': 'stage', 'title_fa': f"{stage.get('name_fa')}: {stage['tasks_fa']}",
                        'timing_fa': 'در این مرحله', 'importance': 'medium',
                        'source': 'Crop Lifecycle Engine (GDD)'})
                if life.get('days_to_harvest') is not None and life['days_to_harvest'] <= 14:
                    entry['tasks'].append({
                        'kind': 'harvest', 'title_fa': f"برداشت نزدیک است — حدود {life['days_to_harvest']} روز مانده",
                        'timing_fa': life.get('estimated_harvest'), 'importance': 'high',
                        'source': 'Crop Lifecycle Engine (GDD)'})
            except Exception:
                pass

            # --- irrigation ---
            try:
                irr = get_irrigation_advice(field)
                if irr.get('advice_fa'):
                    entry['tasks'].append({
                        'kind': 'irrigation', 'title_fa': irr['advice_fa'],
                        'timing_fa': 'این ماه', 'importance': irr.get('importance', 'medium'),
                        'net_need_mm': irr.get('net_need_mm'),
                        'source': 'Irrigation Engine (FAO-56)'})
            except Exception:
                pass

        # --- weather warnings (cached climate engine) ---
        if field.lat is not None and field.lon is not None:
            try:
                from core.services.climate import get_climate_indicators
                d = get_climate_indicators(field.lat, field.lon)
                ind = d.get('indicators', {})
                spi6 = ind.get('spi_6m', {}).get('value')
                hw = ind.get('heatwave', {}).get('value', {})
                if spi6 is not None and spi6 <= -1.5:
                    entry['alerts'].append({
                        'kind': 'drought', 'severity': 'high',
                        'title_fa': f'خشکسالی متوسط تا شدید (SPI-6={spi6:.1f}) — آبیاری را جدی بگیرید',
                        'source': 'NASA POWER → SPI-6'})
                elif spi6 is not None and spi6 <= -1.0:
                    entry['alerts'].append({
                        'kind': 'drought', 'severity': 'medium',
                        'title_fa': f'خشکسالی خفیف (SPI-6={spi6:.1f})',
                        'source': 'NASA POWER → SPI-6'})
                if hw.get('events_ge3days', 0) > 0:
                    entry['alerts'].append({
                        'kind': 'heatwave', 'severity': 'medium',
                        'title_fa': f"{hw['events_ge3days']} رویداد امواج گرما در دوره — از تنش گرمایی محصول محافظت کنید",
                        'source': 'NASA POWER → heatwave'})
            except Exception:
                pass

        # --- stored risk alerts ---
        for a in RiskAlert.objects.filter(field=field, farmer=farmer):
            if a.valid_to and a.valid_to < today:
                continue
            entry['alerts'].append({'kind': a.kind, 'severity': a.severity,
                                    'title_fa': a.title_fa, 'source': a.source or 'engine'})

        if entry['tasks'] or entry['alerts']:
            items.append(entry)

    # --- farmer-level overdue tasks ---
    overdue = FarmTask.objects.filter(farmer=farmer, done=False,
                                      due_date__lt=today).select_related('field')
    overdue_items = [{'id': t.id, 'title': t.title,
                      'field_name': t.field.name if t.field else None,
                      'due_date': t.due_date.isoformat(), 'source': t.source}
                     for t in overdue]

    upcoming = FarmTask.objects.filter(farmer=farmer, done=False,
                                       due_date__gte=today, due_date__lte=today + timedelta(days=3))
    upcoming_items = [{'id': t.id, 'title': t.title,
                       'field_name': t.field.name if t.field else None,
                       'due_date': t.due_date.isoformat(), 'source': t.source}
                      for t in upcoming]

    return {
        'date': today.isoformat(),
        'generated_at': datetime.now().isoformat(timespec='minutes'),
        'fields': items,
        'overdue_tasks': overdue_items,
        'upcoming_tasks': upcoming_items,
        'summary_fa': f"{len(items)} قطعه زمین نیازمند توجه · {len(overdue_items)} کار عقب‌افتاده · {len(upcoming_items)} کار نزدیک",
        'data_sources': ['Crop Lifecycle Engine', 'Irrigation Engine', 'NASA POWER (SPI/heatwave)', 'FarmTask/RiskAlert'],
        'limitations': ['توصیه‌ها rule-based هستند؛ داده خاک و پیش‌بینی هوا در صورت تکمیل دقت را افزایش می‌دهد.'],
    }
