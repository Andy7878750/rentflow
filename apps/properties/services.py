"""Business logic for the properties module."""

import datetime

from django.db import transaction

from apps.tenants.services import apply_share

from .models import Property, PropertyKind

KIND_NAME_MAX = 50


def clean_kind_name(name):
    """'  гараж   у  дома ' → 'Гараж у дома'."""
    name = ' '.join((name or '').split())[:KIND_NAME_MAX]
    return name[:1].upper() + name[1:]


def add_custom_kind(owner, name):
    """Add the landlord's own object type. Returns (kind, error); an existing one is reused."""
    name = clean_kind_name(name)
    if not name:
        return None, 'Введите название.'
    built_in = {label.casefold() for value, label in Property.Kind.choices if value != Property.Kind.CUSTOM}
    if name.casefold() in built_in:
        return None, 'Такой вариант уже есть в списке.'
    # Compared in Python: SQLite's case-insensitive match only knows Latin letters.
    for existing in PropertyKind.objects.filter(owner=owner):
        if existing.name.casefold() == name.casefold():
            return existing, None
    return PropertyKind.objects.create(owner=owner, name=name), None

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


@transaction.atomic
def save_property(form, tenant_formset, owner):
    """Save the object and its tenants, deriving each tenant's share in the other unit."""
    property_obj = form.save(commit=False)
    if property_obj.owner_id is None:
        property_obj.owner = owner
    property_obj.save()

    if property_obj.kind == Property.Kind.CUSTOM:
        add_custom_kind(owner, property_obj.custom_kind)  # keep it in the landlord's list

    if property_obj.is_owner_used:
        # The landlord uses the object themselves: nobody else shares the bills.
        property_obj.tenants.all().delete()
        return property_obj

    for tenant_form in tenant_formset.forms:
        tenant = tenant_form.instance
        if tenant_form in tenant_formset.deleted_forms:
            if tenant.pk:
                tenant.delete()
            continue
        if not (tenant.pk or tenant_form.has_changed()):
            continue  # untouched empty row
        tenant = tenant_form.save(commit=False)
        tenant.property = property_obj
        apply_share(tenant, tenant_form.cleaned_data['share'], property_obj.share_unit, property_obj.area)
        tenant.save()
    return property_obj
