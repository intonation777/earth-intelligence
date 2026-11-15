"""PDF report generation for climate indicators (reportlab).

Uses Tahoma (supports Persian) when available; falls back to Helvetica.
All values come from the Climate Engine — no synthetic data.
"""
import io
import os

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

_FONT_CANDIDATES = [
    r'C:\Windows\Fonts\tahoma.ttf',
    r'C:\Windows\Fonts\tahomabd.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
]


def _register_font():
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont('ReportFont', path))
                return 'ReportFont'
            except Exception:
                continue
    return 'Helvetica'


def build_climate_pdf(data):
    """Build a PDF report from get_climate_indicators() output."""
    font = _register_font()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm,
                            title='Climate Intelligence Report')
    styles = {
        'title': ParagraphStyle('title', fontName=font, fontSize=16, leading=20,
                                textColor=colors.HexColor('#10243a'), spaceAfter=6),
        'h2': ParagraphStyle('h2', fontName=font, fontSize=12, leading=16,
                             textColor=colors.HexColor('#087f8c'), spaceBefore=10, spaceAfter=4),
        'body': ParagraphStyle('body', fontName=font, fontSize=9.5, leading=13,
                               textColor=colors.HexColor('#17212f')),
        'small': ParagraphStyle('small', fontName=font, fontSize=8, leading=11,
                                textColor=colors.HexColor('#64748b')),
    }
    story = []
    loc = data.get('location', {})
    per = data.get('period', {})
    story.append(Paragraph('گزارش هوش اقلیمی — Climate Intelligence Report', styles['title']))
    story.append(Paragraph(
        f"موقعیت: {loc.get('lat')} ، {loc.get('lon')} &nbsp;|&nbsp; "
        f"دوره: {per.get('start')} تا {per.get('end')} ({per.get('months')} ماه) &nbsp;|&nbsp; "
        f"منبع: {data.get('source')} &nbsp;|&nbsp; دریافت: {(data.get('fetched_at') or '')[:10]}",
        styles['small']))
    story.append(Spacer(1, 6))

    # indicators table
    story.append(Paragraph('شاخص‌های اقلیمی', styles['h2']))
    ind = data.get('indicators', {})
    rows = [['شاخص', 'مقدار', 'واحد', 'فرمول']]
    labels = {
        'temperature_anomaly_c': 'آنومالی دما', 'precipitation_anomaly_pct': 'آنومالی بارش',
        'spi_1m': 'SPI-1', 'spi_3m': 'SPI-3', 'spi_6m': 'SPI-6', 'spi_12m': 'SPI-12',
        'spei_1m': 'SPEI-1', 'spei_3m': 'SPEI-3', 'spei_6m': 'SPEI-6', 'spei_12m': 'SPEI-12',
        'heatwave': 'امواج گرما', 'frost_days': 'روزهای یخبندان',
        'max_consecutive_dry_days': 'طولانی‌ترین خشکی', 'gdd_base10': 'GDD پایه ۱۰°',
        'water_balance': 'تراز آب',
    }
    for key, label in labels.items():
        it = ind.get(key)
        if not it:
            continue
        v = it.get('value')
        if isinstance(v, dict):
            v = ' / '.join(f'{kk}={vv}' for kk, vv in v.items())
        rows.append([label, '—' if v is None else str(v), it.get('unit', ''),
                     (it.get('formula') or '')[:60]])
    t = Table(rows, colWidths=[45 * mm, 35 * mm, 20 * mm, 75 * mm])
    t.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), font), ('FONTSIZE', (0, 0), (-1, -1), 8.5),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#10243a')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#dce4eb')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f3f6f8')]),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    story.append(t)
    story.append(Spacer(1, 8))

    # monthly table (last 12 months)
    monthly = (data.get('monthly') or [])[-12:]
    if monthly:
        story.append(Paragraph('۱۲ ماه اخیر', styles['h2']))
        rows = [['ماه', 'میانگین دما (°C)', 'بارش (mm)', 'PET (mm)', 'تراز آب (mm)']]
        for m in monthly:
            rows.append([m['month'],
                         '—' if m.get('tmean_c') is None else str(m['tmean_c']),
                         str(m.get('precip_mm', '—')),
                         str(m.get('pet_mm', '—')),
                         str(m.get('water_balance_mm', '—'))])
        t = Table(rows, colWidths=[28 * mm, 32 * mm, 30 * mm, 30 * mm, 30 * mm])
        t.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), font), ('FONTSIZE', (0, 0), (-1, -1), 8.5),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#087f8c')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#dce4eb')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f3f6f8')]),
        ]))
        story.append(t)
        story.append(Spacer(1, 8))

    # limitations
    lims = data.get('limitations') or []
    if lims:
        story.append(Paragraph('محدودیت‌های روش‌شناختی', styles['h2']))
        for l in lims:
            story.append(Paragraph(f'• {l}', styles['small']))
    story.append(Spacer(1, 10))
    story.append(Paragraph(
        'این گزارش فقط از داده‌های واقعی NASA POWER تولید شده است. '
        'منبع: NASA POWER API · موتور هوش اقلیمی', styles['small']))
    doc.build(story)
    return buf.getvalue()
