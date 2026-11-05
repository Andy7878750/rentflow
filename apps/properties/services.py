"""Business logic for the properties module."""

import datetime

MONTH_NAMES = [
    'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
    'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
]


def parse_month(value, today=None):
    """Turn '2026-10' into date(2026, 10, 1); fall back to the current month."""
    today = today or datetime.date.today()
    try:
        year, month = (int(part) for part in (value or '').split('-'))
        return datetime.date(year, month, 1)
    except ValueError:
        return today.replace(day=1)


def shift_month(month, delta):
    """Move a first-of-month date by `delta` months."""
    index = month.year * 12 + (month.month - 1) + delta
    return datetime.date(index // 12, index % 12 + 1, 1)


def month_param(month):
    return f'{month.year:04d}-{month.month:02d}'


def month_label(month):
    return f'{MONTH_NAMES[month.month - 1]} {month.year}'
