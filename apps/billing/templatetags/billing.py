from django import template
from django.utils.html import format_html

from apps.billing import services
from apps.billing.services import fmt_number

register = template.Library()


@register.filter
def bill_groups(payer):
    """A payer's bill lines in groups: «Общие · по долям 45%» and «По счётчикам»."""
    return services.bill_groups(payer)


@register.filter
def meter_rows(line):
    """Under a meter's bill line: «счётчик № … · тариф …» and «было … → стало … = …»."""
    return services.bill_meter_rows(line)


@register.simple_tag
def bill_share(payer, title, month_label):
    """The bill as a message (WhatsApp / Telegram) and the PDF file's name, for «Поделиться»."""
    return {'text': services.bill_text(payer, title, month_label), 'file': services.bill_file_name(title, month_label)}


@register.filter
def money_words(value):
    """A sum in words: «Одиннадцать тысяч семьсот пять рублей 80 копеек»."""
    return services.money_words(value)


@register.filter
def tenant_share(tenant):
    """The tenant's share in both units (2026-11-24): «45% · 49,5 м²» — the object's own unit first, the other grey
    after it; only one when the other is not known. The bill shows only what the split used — not this."""
    percent = f'{fmt_number(tenant.share_percent)}%' if tenant.share_percent is not None else ''
    area = f'{fmt_number(tenant.area)}\xa0м²' if tenant.area is not None else ''
    main, alt = (area, percent) if tenant.property.share_unit == 'area' else (percent, area)
    if not main:
        main, alt = alt, ''
    if not main:
        return '—'
    if not alt:
        return main
    return format_html('{}<span class="share-alt"> · {}</span>', main, alt)


@register.filter
def num(value):
    """A number for an input field: 6.5000 → '6,5', 4200.00 → '4 200', None → ''."""
    if value is None or value == '':
        return ''
    return fmt_number(value)
