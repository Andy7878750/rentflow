from django import template

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
def num(value):
    """A number for an input field: 6.5000 → '6,5', 4200.00 → '4 200', None → ''."""
    if value is None or value == '':
        return ''
    return fmt_number(value)
