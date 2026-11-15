"""Agricultural Economics — cost, revenue, profit, break-even.

Prices are NEVER invented: the user supplies price_per_unit and optional
yield. If missing, the engine reports cost-only and break-even yield at
the given price, with honest limitations.
"""
from ..models import Farm, FarmExpense, Field

CATEGORY_FA = {'seed': 'بذر', 'land': 'آماده‌سازی', 'water': 'آب', 'fertilizer': 'کود',
               'pesticide': 'سم', 'labor': 'نیروی کار', 'harvest': 'برداشت',
               'transport': 'حمل‌ونقل', 'other': 'سایر'}


def get_economics(farm, yield_kg_ha=None, price_per_unit=None, area_ha=None):
    """Economics summary for a farm. yield_kg_ha & price are user inputs."""
    expenses = FarmExpense.objects.filter(farm=farm)
    total_cost = sum(e.amount for e in expenses)
    by_category = {}
    for e in expenses:
        by_category[e.category] = by_category.get(e.category, 0) + e.amount

    fields = Field.objects.filter(farm=farm)
    total_area = area_ha if area_ha else sum(f.area_ha or 0 for f in fields)
    cost_per_ha = round(total_cost / total_area, 1) if total_area else None

    out = {
        'farm_id': farm.id, 'farm_name': farm.name,
        'total_cost': round(total_cost, 1),
        'cost_per_ha': cost_per_ha,
        'total_area_ha': total_area,
        'expenses_by_category': [{'category': k, 'category_fa': CATEGORY_FA.get(k, k),
                                  'amount': round(v, 1)} for k, v in sorted(by_category.items(), key=lambda x: -x[1])],
        'expense_count': expenses.count(),
        'limitations_fa': [],
    }

    # --- revenue / profit (only if user provides yield + price) ---
    if yield_kg_ha is not None and price_per_unit is not None and total_area:
        total_yield = yield_kg_ha * total_area
        revenue = total_yield * price_per_unit
        profit = revenue - total_cost
        margin = round(profit / revenue * 100, 1) if revenue else None
        break_even_yield = round(total_cost / (price_per_unit * total_area), 1) if price_per_unit else None
        out.update({
            'yield_kg_ha': yield_kg_ha, 'price_per_unit': price_per_unit,
            'total_yield_kg': round(total_yield, 1),
            'revenue': round(revenue, 1), 'profit': round(profit, 1),
            'margin_pct': margin, 'break_even_yield_kg_ha': break_even_yield,
            'scenarios': [
                {'name': 'pessimistic', 'yield_factor': 0.7,
                 'profit': round(revenue * 0.7 - total_cost, 1)},
                {'name': 'expected', 'yield_factor': 1.0, 'profit': round(profit, 1)},
                {'name': 'optimistic', 'yield_factor': 1.3,
                 'profit': round(revenue * 1.3 - total_cost, 1)},
            ],
        })
    else:
        out['limitations_fa'].append('برای محاسبه درآمد و سود، عملکرد (kg/ha) و قیمت فروش را وارد کنید — قیمت ساختگی ارائه نمی‌شود.')
        if price_per_unit and total_area:
            out['break_even_yield_kg_ha'] = round(total_cost / (price_per_unit * total_area), 1)
            out['limitations_fa'].append(f'نقطه سربه‌سر در قیمت {price_per_unit}: {out["break_even_yield_kg_ha"]} kg/ha')

    if not total_area:
        out['limitations_fa'].append('مساحت زمین‌ها ثبت نشده — هزینه بر هکتار محاسبه نشد.')
    out['limitations_fa'].append('قیمت‌ها و عملکرد باید توسط کاربر وارد شوند؛ این ماژول قیمت بازار را حدس نمی‌زند.')
    return out
