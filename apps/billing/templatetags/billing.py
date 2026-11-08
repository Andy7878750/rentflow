from django import template

from apps.billing.services import fmt_number

register = template.Library()


@register.filter
def num(value):
    """A number for an input field: 6.5000 → '6,5', 4200.00 → '4 200', None → ''."""
    if value is None or value == '':
        return ''
    return fmt_number(value)
