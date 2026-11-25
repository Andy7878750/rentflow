"""«Счёт PDF»: a payer's bill for the month as a real PDF file, A4, wide margins.

2026-11-25 (docs/mockups/2026-11-25-bill-pdf.html, «примерно» as an Estonian KÜ bill): the landlord on the left and
the bill's date, period and «Оплатить до» on the right; «Плательщик» and «Объект»; one table «Услуга · Ед. · Кол-во ·
Тариф, ₽ · Сумма, ₽» (Кол-во × Тариф = Сумма — «простое округление»; the coefficient is inside the tariff, never
named); the total on the right (with VAT when the tenant's bill has it) and the sum in words.
The font is Roboto (static/fonts, Cyrillic and ₽), DejaVu Sans for the signs Roboto lacks. Black and grey only;
every text on one left and one right edge (PAD inside the lines and the grey heads).
"""
import calendar
from datetime import date
from pathlib import Path

from django.conf import settings
from fpdf import FPDF

from . import services

FONTS = Path(settings.BASE_DIR) / 'static' / 'fonts'
BLACK = (20, 20, 20)
GREY = (125, 125, 125)
BORDER = (225, 225, 225)
HEAD_BG = (243, 243, 243)
MARGIN = 22   # mm — «при печати взять более толстые поля»
PAD = 2.5     # mm, the text inside the lines and the grey heads
# the table's columns (mm), the name takes the rest
COL_UNIT, COL_QTY, COL_PRICE, COL_SUM = 14, 24, 28, 28  # wide enough for «520 / 310»
TEXT, SMALL, CAPS, TITLE = 6.5, 5.4, 4.9, 12  # pt
MONTHS_GEN = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября',
              'ноября', 'декабря']


def _money(value):
    return services.fmt_number(value, 2)


def due_date(month, day):
    """«Оплатить до 10 числа» of the month after the bill's one; a short month — its last day."""
    year, number = (month.year + 1, 1) if month.month == 12 else (month.year, month.month + 1)
    return date(year, number, min(day, calendar.monthrange(year, number)[1]))


def line_sub(line):
    """The grey row under a service in the table: the meter's № and readings, or how it was counted. A line with a
    coefficient shows no formula — the coefficient is not named in the tenant's bill."""
    meter, reading = line.meter, line.reading
    if meter is not None:
        text = f'счётчик № {meter.serial}' if meter.serial else 'счётчик'
        if reading is not None and getattr(reading, 'previous', None) is not None and reading.current is not None:
            text += f' · {services.fmt_number(reading.previous)} → {services.fmt_number(reading.current)}'
            if line.qty_night is not None and getattr(reading, 'previous_night', None) is not None \
                    and reading.current_night is not None:  # day / night — like the columns: «500 → 700 / 700 → 790»
                text += f' / {services.fmt_number(reading.previous_night)} → {services.fmt_number(reading.current_night)}'
        return text
    if line.qty is not None or line.k != 1:
        return ''
    return line.formula


def line_cols(line):
    """(Ед., Кол-во, Тариф) of a table row; empty when the line has no such columns (a formula, day / night)."""
    if line.qty is None:
        return '', '', ''
    qty = services.fmt_number(line.qty.normalize() if line.per == 1 else line.qty.quantize(services.CENT).normalize())
    price = _money(line.price)
    if line.qty_night is not None:  # day / night in one row: «520 / 310» · «6,10 / 2,40»
        qty += ' / ' + services.fmt_number(line.qty_night.normalize())
        price += ' / ' + _money(line.price_night)
    return line.unit, qty, price


class _Bill(FPDF):
    def __init__(self):
        super().__init__(format='A4')
        self.add_font('Main', '', str(FONTS / 'Roboto-Regular.ttf'))
        self.add_font('Main', 'B', str(FONTS / 'Roboto-Bold.ttf'))
        self.add_font('DejaVu', '', str(FONTS / 'DejaVuSans.ttf'))
        self.add_font('DejaVu', 'B', str(FONTS / 'DejaVuSans-Bold.ttf'))
        self.set_fallback_fonts(['DejaVu'])
        self.set_margins(MARGIN, MARGIN, MARGIN)
        self.set_auto_page_break(True, margin=MARGIN)
        self.c_margin = 0
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


def bill_pdf(property_obj, bill, payer, title, month_label, today, month=None, landlord='', owner_req=None, number=None):
    """owner_req — the landlord's Requisites (accounts) or None; number — the issued bill's №, None — not issued yet."""
    pdf = _Bill()
    full = pdf.w - 2 * MARGIN
    x0, inner = MARGIN + PAD, full - 2 * PAD
    half = inner / 2
    tenant = payer.tenant
    requisites = bool(tenant and tenant.bill_requisites)
    pdf.set_title(f'Счёт · {title} · {month_label}')

    # ---- the landlord (left) · «Счёт», date, period, «Оплатить до» (right)
    top = pdf.get_y()
    kv = [('Дата', f'{today:%d.%m.%Y}'), ('Период', month_label)]
    if tenant and tenant.due_on and month is not None:
        kv.append(('Оплатить до', f'{due_date(month, tenant.due_day):%d.%m.%Y}'))
    pdf.set_xy(x0, top)
    pdf.text_at(CAPS, GREY, 'АРЕНДОДАТЕЛЬ', width=half, height=2.6)
    use_req = bool(requisites and owner_req)
    pdf.set_xy(x0, top + 3)
    pdf.text_at(TEXT + 1, BLACK, (owner_req.legal_name if use_req and owner_req.legal_name else landlord) or '—',
                bold=True, width=half, height=3.6)
    if use_req:  # 2026-11-25: «Ваши реквизиты» under the name
        ogrn = owner_req.ogrn and (f'ОГРНИП {owner_req.ogrn}' if len(owner_req.ogrn) == 15 else f'ОГРН {owner_req.ogrn}')
        rows = [' · '.join(x for x in (owner_req.inn and f'ИНН {owner_req.inn}', owner_req.kpp and f'КПП {owner_req.kpp}', ogrn) if x),
                owner_req.address, ' · '.join(x for x in (owner_req.phone, owner_req.email) if x)]
        pdf.set_font('Main', '', TEXT)
        pdf.set_text_color(*GREY)
        pdf.set_xy(x0, top + 7)
        for text in [r for r in rows if r]:
            pdf.set_x(x0)
            pdf.multi_cell(half - 4, 2.9, text)
    landlord_bottom = pdf.get_y()
    pdf.set_xy(x0 + half, top)
    pdf.text_at(TITLE, BLACK, f'Счёт № {number}' if number else 'Счёт', bold=True, width=half, align='R', height=5)
    y = top + 6.5
    for label, value in kv:
        pdf.set_xy(x0 + half, y)
        pdf.text_at(TEXT, GREY, label, width=half - 30, align='R', height=3.2)
        pdf.text_at(TEXT, BLACK, value, bold=label == 'Оплатить до', width=30, align='R', height=3.2)
        y += 3.4
    pdf.set_y(max(y, top + 8, landlord_bottom) + 3)
    pdf.rule(BLACK, 0.3)
    pdf.ln(3.5)

    # ---- «Плательщик» · «Объект»
    top = pdf.get_y()
    pdf.set_xy(x0, top)
    pdf.text_at(CAPS, GREY, 'ПЛАТЕЛЬЩИК', width=half, height=2.6)
    pdf.text_at(CAPS, GREY, 'ОБЪЕКТ', width=half, height=2.6)
    name = (tenant.legal_name or tenant.name) if tenant else title
    pdf.set_xy(x0, top + 3)
    pdf.text_at(TEXT + 0.7, BLACK, name, bold=True, width=half - 4, height=3.4)
    pdf.set_xy(x0 + half, top + 3)  # «Объект» — its own column, the same left edge as its caption
    pdf.text_at(TEXT + 0.7, BLACK, property_obj.name, bold=True, width=half, height=3.4)
    left = []
    if requisites:
        ids = ' · '.join(part for part in (f'ИНН {tenant.inn}' if tenant.inn else '', f'КПП {tenant.kpp}' if tenant.kpp else '') if part)
        left += [ids, tenant.legal_address]
    if tenant:
        share = []
        if tenant.share_percent is not None:
            share.append(f'Доля {services.fmt_number(tenant.share_percent)}%')
        if tenant.area is not None:
            share.append(f'{services.fmt_number(tenant.area)} м²')
        left.append(' · '.join(share))
    pdf.set_font('Main', '', TEXT)
    pdf.set_text_color(*GREY)
    pdf.set_xy(x0, top + 7)
    for text in [t for t in left if t]:
        pdf.set_x(x0)
        pdf.multi_cell(half - 4, 2.9, text)
    bottom = pdf.get_y()
    if property_obj.address:
        pdf.set_xy(x0 + half, top + 7)
        pdf.multi_cell(half, 2.9, property_obj.address)
    pdf.set_y(max(bottom, pdf.get_y(), top + 9) + 5)

    # ---- the table
    name_w = inner - COL_UNIT - COL_QTY - COL_PRICE - COL_SUM
    pdf.set_fill_color(*HEAD_BG)
    pdf.rect(MARGIN, pdf.get_y(), full, 5, style='F')
    pdf.set_x(x0)
    for text, width, align in (('УСЛУГА', name_w, 'L'), ('ЕД.', COL_UNIT, 'R'), ('КОЛ-ВО', COL_QTY, 'R'),
                               ('ТАРИФ, ₽', COL_PRICE, 'R'), ('СУММА, ₽', COL_SUM, 'R')):
        pdf.text_at(CAPS, GREY, text, width=width, align=align, height=5)
    pdf.ln(5)
    for line in payer.lines:
        unit, qty, price = line_cols(line)
        pdf.ln(1.6)
        pdf.set_x(x0)
        pdf.text_at(TEXT, BLACK, line.receipt.name, width=name_w, height=3.2)
        pdf.text_at(TEXT, BLACK, unit, width=COL_UNIT, align='R', height=3.2)
        pdf.text_at(TEXT, BLACK, qty, width=COL_QTY, align='R', height=3.2)
        pdf.text_at(TEXT, BLACK, price, width=COL_PRICE, align='R', height=3.2)
        pdf.text_at(TEXT, BLACK, _money(line.amount), width=COL_SUM, align='R', height=3.2)
        pdf.ln(3.4)
        sub = line_sub(line)
        if sub:
            pdf.set_x(x0)
            pdf.set_font('Main', '', SMALL)
            pdf.set_text_color(*GREY)
            pdf.multi_cell(name_w - 2, 2.5, sub)
        pdf.ln(1.4)
        pdf.rule()
    if not payer.lines:
        pdf.ln(2)
        pdf.set_x(x0)
        pdf.text_at(TEXT, GREY, 'За этот месяц пока нечего начислять.', height=3.5)
        pdf.ln(4)

    # ---- the total on the right: «Итого» (with VAT) · «К оплате»
    vat = services.bill_vat(payer)
    rows = []
    if vat and vat['mode'] == 'top':
        rows += [('Итого без НДС', _money(vat['net'])), (f'НДС {vat["rate"]}%', _money(vat['vat']))]
    else:
        rows.append(('Итого', _money(payer.total)))
        if vat:
            rows.append((f'в т. ч. НДС {vat["rate"]}%', _money(vat['vat'])))
        elif requisites:
            rows.append(('НДС', 'не облагается'))
    pay = vat['pay'] if vat else payer.total
    label_w, sum_w = 40, COL_SUM
    lx = x0 + inner - label_w - sum_w
    pdf.ln(3)
    for label, value in rows:
        pdf.set_x(lx)
        pdf.text_at(TEXT, GREY, label, width=label_w, align='R', height=3.4)
        pdf.text_at(TEXT, BLACK if value != 'не облагается' else GREY, value, width=sum_w, align='R', height=3.4)
        pdf.ln(3.6)
    pdf.set_draw_color(*BLACK)
    pdf.set_line_width(0.3)
    y = pdf.get_y() + 0.8
    pdf.line(lx, y, x0 + inner + PAD, y)
    pdf.set_y(y + 1.6)
    pdf.set_x(lx)
    pdf.text_at(TEXT + 1.5, BLACK, 'К оплате, ₽', bold=True, width=label_w, align='R', height=4)
    pdf.text_at(TEXT + 1.5, BLACK, _money(pay), bold=True, width=sum_w, align='R', height=4)
    pdf.ln(6)
    pdf.set_x(x0)
    pdf.set_font('Main', '', TEXT)
    pdf.set_text_color(*GREY)
    words = services.money_words(pay) + '.'
    if requisites and not vat:
        words += ' НДС не облагается.'
    pdf.multi_cell(inner, 3, words)
    if bill.missing:
        pdf.ln(2.5)
        names = ', '.join(receipt.name for receipt in bill.missing)
        pdf.set_fill_color(*HEAD_BG)
        pdf.set_x(MARGIN)
        pdf.multi_cell(full, 4, f'  Ещё не введено: {names} — счёт неполный.', fill=True)
    if use_req and owner_req.has_bank:
        # «Реквизиты для оплаты» (2026-11-25): a grey head over the full width, label · value rows, the purpose
        pdf.ln(6)
        pdf.set_fill_color(*HEAD_BG)
        pdf.rect(MARGIN, pdf.get_y(), full, 5, style='F')
        pdf.set_x(x0)
        pdf.text_at(CAPS, GREY, 'РЕКВИЗИТЫ ДЛЯ ОПЛАТЫ', width=inner, height=5)
        pdf.ln(6.5)
        receiver = ', '.join(x for x in (owner_req.legal_name or landlord, owner_req.inn and f'ИНН {owner_req.inn}',
                                         owner_req.kpp and f'КПП {owner_req.kpp}') if x)
        vat_word = ('НДС не облагается' if not vat else
                    f'{"в т. ч. " if vat["mode"] == "in" else ""}НДС {vat["rate"]}% — {_money(vat["vat"])} ₽')
        purpose = (f'Оплата по счёту {"№ " + str(number) + " " if number else ""}от {today:%d.%m.%Y} '
                   f'за коммунальные услуги, {month_label.lower()}, {vat_word}')
        label_col = 34
        for label, value in (('Получатель', receiver), ('Расчётный счёт', owner_req.account), ('Банк', owner_req.bank),
                             ('БИК · Корр. счёт', ' · '.join(x for x in (owner_req.bik, owner_req.corr_account) if x)),
                             ('Назначение платежа', purpose)):
            y = pdf.get_y()
            pdf.set_x(x0)
            pdf.text_at(TEXT, GREY, label, width=label_col, height=3.1)
            pdf.set_xy(x0 + label_col, y)
            pdf.set_font('Main', '', TEXT)
            pdf.set_text_color(*BLACK)
            pdf.multi_cell(inner - label_col, 3.1, value)
            pdf.ln(0.6)
        pdf.ln(1)
        pdf.rule()
    if requisites:
        pdf.ln(14)
        y = pdf.get_y()
        pdf.set_draw_color(*GREY)
        pdf.set_line_width(0.2)
        pdf.line(x0, y, x0 + half - 6, y)
        pdf.line(x0 + half, y, x0 + inner, y)
        pdf.set_y(y + 1)
        pdf.set_x(x0)
        pdf.text_at(SMALL, GREY, 'Арендодатель', width=half, height=2.6)
        pdf.text_at(SMALL, GREY, 'Подпись', width=half, height=2.6)
    return bytes(pdf.output())
