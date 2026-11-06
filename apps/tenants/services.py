"""Tenant shares: the landlord enters them in % or in m², the other unit is derived."""

from decimal import ROUND_HALF_UP, Decimal

HUNDRED = Decimal('100')
CENT = Decimal('0.01')


def _round(value):
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def percent_from_area(area, total_area):
    """27 m² of 60 m² → 45.00 %. None when the object's area is unknown."""
    if area is None or not total_area:
        return None
    return _round(area / total_area * HUNDRED)


def area_from_percent(percent, total_area):
    """45 % of 60 m² → 27.00 m². None when the object's area is unknown."""
    if percent is None or not total_area:
        return None
    return _round(percent * total_area / HUNDRED)


def plain(value):
    """Drop trailing zeros without scientific notation: 60.00 → 60, 27.50 → 27.5."""
    if value is None:
        return None
    return Decimal(f'{value.normalize():f}')


def fmt(value):
    """45.50 → '45,5' for messages."""
    return f'{plain(value)}'.replace('.', ',')


def apply_share(tenant, value, unit, total_area):
    """Store the entered share on the tenant and derive the other unit."""
    if unit == 'area':
        tenant.area = value
        tenant.share_percent = percent_from_area(value, total_area)
    else:
        tenant.share_percent = value
        tenant.area = area_from_percent(value, total_area)


def share_error(values, unit, total_area):
    """Why the entered shares don't fit the object, or None when they do."""
    occupied = sum(values, Decimal('0'))
    if unit == 'area':
        if not total_area:
            return 'Чтобы указать доли в м², заполните площадь объекта.'
        if occupied > total_area:
            return f'Арендаторы занимают {fmt(occupied)} м² — больше площади объекта ({fmt(total_area)} м²).'
    elif occupied > HUNDRED:
        return f'Сумма долей {fmt(occupied)}% — больше 100%.'
    return None
