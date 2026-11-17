"""«Счёт PDF» (2026-11-17): a payer's bill for the month as a real PDF file, A4, wide margins.

The same content as the bill on the object page: groups («Общие · по долям 45%», «По счётчикам»), each line with
its meter rows, «Итого к оплате» and the sum in words. The font is Roboto (in static/fonts, with Cyrillic and ₽), DejaVu Sans for the signs Roboto lacks.
Small, like a printed document (2026-11-17, the user three times: «очень крупно», «итог громоздко», «ещё на 30%»):
sizes 4.5–8.4pt; bold only for the title, the names in the parties and the total. Black and grey only.
"""
from pathlib import Path

from django.conf import settings
from fpdf import FPDF

from . import services

FONTS = Path(settings.BASE_DIR) / 'static' / 'fonts'
# Two colours only (2026-11-17, the user): black and grey; the grey head and the thin lines are pale grey.
BLACK = (20, 20, 20)
GREY = (125, 125, 125)
PRIMARY = TEXT = BLACK
MUTED = LIGHT = WARN = GREY
BORDER = (225, 225, 225)
HEAD_BG = WARN_BG = (243, 243, 243)
# Every size and vertical step below is × 0.7 of the previous version (2026-11-17: «уменьши ещё на 30%»).
MARGIN = 22  # mm — «при печати взять более толстые поля»
SUM_W = 32   # mm, the sums column
PAD = 2.5    # mm, the inner indent of the rows


def _money(value):
    return services.fmt_number(value, 2)


class _Bill(FPDF):
    def __init__(self):
        super().__init__(format='A4')
        # Roboto (2026-11-17, the user's choice over DejaVu Sans). It has no «→» — that and any other missing sign
        # comes from DejaVu Sans (fallback).
        self.add_font('Main', '', str(FONTS / 'Roboto-Regular.ttf'))
        self.add_font('Main', 'B', str(FONTS / 'Roboto-Bold.ttf'))
        self.add_font('DejaVu', '', str(FONTS / 'DejaVuSans.ttf'))
        self.add_font('DejaVu', 'B', str(FONTS / 'DejaVuSans-Bold.ttf'))
        self.set_fallback_fonts(['DejaVu'])
        self.set_margins(MARGIN, MARGIN, MARGIN)
        self.set_auto_page_break(True, margin=MARGIN)
        self.add_page()

    def text_at(self, size, color, text, bold=False, width=0, align='L', height=None):
        self.set_font('Main', 'B' if bold else '', size)
        self.set_text_color(*color)
        self.cell(width, height or size * 0.42, text, align=align)

    def rule(self, color=BORDER, width=0.2):
        self.set_draw_color(*color)
        self.set_line_width(width)
        y = self.get_y()
        self.line(self.l_margin, y, self.w - self.r_margin, y)


def bill_pdf(property_obj, bill, payer, title, month_label, today):
    pdf = _Bill()
    full = pdf.w - 2 * MARGIN
    # One left and one right edge for ALL the text (2026-11-17, the user: «слева как кривые зубы»): the text stands
    # PAD inside the lines and the grey heads, which run the full width; fpdf's own cell padding is off.
    pdf.c_margin = 0
    x0, inner = MARGIN + PAD, full - 2 * PAD
    half = inner / 2
    pdf.set_title(f'Счёт · {title} · {month_label}')

    # Title, the date on the right
    pdf.set_x(x0)
    pdf.text_at(8.4, PRIMARY, f'Счёт за {month_label.lower()}', bold=True, width=inner * 0.7, height=4.2)
    pdf.text_at(5.6, MUTED, f'от {today:%d.%m.%Y}', width=inner * 0.3, align='R', height=4.2)
    pdf.ln(7)
    pdf.rule(PRIMARY, 0.3)
    pdf.ln(3.5)

    # Кому / Объект
    y = pdf.get_y()
    pdf.set_x(x0)
    pdf.text_at(4.55, MUTED, 'КОМУ', width=half)
    pdf.text_at(4.55, MUTED, 'ОБЪЕКТ', width=half)
    pdf.ln(2.8)
    pdf.set_x(x0)
    pdf.text_at(6.3, TEXT, title, bold=True, width=half)
    pdf.text_at(6.3, TEXT, property_obj.name, bold=True, width=half)
    pdf.ln(3.22)
    if property_obj.address:
        pdf.set_x(x0 + half)
        pdf.set_font('Main', '', 5.25)
        pdf.set_text_color(*MUTED)
        pdf.multi_cell(half, 2.52, property_obj.address)
    pdf.set_y(max(pdf.get_y(), y + 8.4) + 2.8)

    groups = services.bill_groups(payer)
    for group in groups:
        # The group's grey head: «ОБЩИЕ · ПО ДОЛЯМ 45%» · «СУММА, ₽»
        pdf.set_fill_color(*HEAD_BG)
        pdf.rect(MARGIN, pdf.get_y(), full, 4.2, style='F')
        pdf.set_x(x0)
        pdf.text_at(4.55, MUTED, group['title'].upper(), width=inner - SUM_W, height=4.2)
        pdf.text_at(4.55, MUTED, 'СУММА, ₽', width=SUM_W, align='R', height=4.2)
        pdf.ln(4.2)
        for line in group['lines']:
            pdf.ln(1.4)
            pdf.set_x(x0)
            pdf.text_at(5.95, TEXT, line.receipt.name, width=inner - SUM_W, height=3.08)
            pdf.text_at(5.95, TEXT, _money(line.amount), width=SUM_W, align='R', height=3.08)
            pdf.ln(3.36)
            for row in services.bill_meter_rows(line) or [line.formula]:
                pdf.set_x(x0)
                pdf.set_font('Main', '', 5.25)
                pdf.set_text_color(*MUTED)
                pdf.multi_cell(inner - SUM_W, 2.52, row)
            pdf.ln(1.4)
            pdf.rule()
        pdf.ln(2.8)

    if not groups:
        pdf.set_x(x0)
        pdf.text_at(6.3, MUTED, 'За этот месяц пока нечего начислять.', height=3.5)
        pdf.ln(4.9)

    # Итого
    pdf.rule(PRIMARY, 0.3)
    pdf.ln(2.1)
    pdf.set_x(x0)
    pdf.text_at(6.3, PRIMARY, 'Итого к оплате', bold=True, width=half, height=3.5)
    pdf.text_at(7, PRIMARY, f'{_money(payer.total)} ₽', bold=True, width=half, align='R', height=3.5)
    pdf.ln(4.2)
    pdf.set_x(x0)
    pdf.set_font('Main', '', 5.25)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(inner, 2.66, services.money_words(payer.total) + '.')
    if bill.missing:
        pdf.ln(2.1)
        names = ', '.join(receipt.name for receipt in bill.missing)
        pdf.set_fill_color(*WARN_BG)
        pdf.set_text_color(*WARN)
        pdf.set_x(MARGIN)
        pdf.multi_cell(full, 3.5, f'  Ещё не введено: {names} — счёт неполный.', fill=True)
    return bytes(pdf.output())
