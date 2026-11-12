"""Business logic for the properties module."""

import datetime

from django.db import transaction

from apps.billing.services import resync_property
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


def setup_steps(property_obj):
    """The one-time setup checklist shown on the object card until everything is done."""
    if property_obj.is_owner_used:
        people = ('Собственник', True)
    else:
        people = ('Арендаторы', bool(property_obj.tenants.all()))
    steps = [
        {'label': 'Объект', 'done': True},
        {'label': people[0], 'done': people[1]},
        {'label': 'Услуги и счётчики', 'done': bool(property_obj.receipts.all())},
    ]
    return {
        'steps': steps,
        'done': sum(step['done'] for step in steps),
        'total': len(steps),
        'complete': all(step['done'] for step in steps),
    }


@transaction.atomic
def save_property(form, tenant_formset, owner, meter_formset=None):
    """Save the object, its tenants (deriving each share in the other unit) and its meters."""
    property_obj = form.save(commit=False)
    if property_obj.owner_id is None:
        property_obj.owner = owner
    property_obj.save()

    if property_obj.kind == Property.Kind.CUSTOM:
        add_custom_kind(owner, property_obj.custom_kind)  # keep it in the landlord's list

    if property_obj.is_owner_used:
        # The landlord uses the object themselves: nobody else shares the bills.
        property_obj.tenants.all().delete()
        tenant_keys = {}
    else:
        tenant_keys = _save_tenant_rows(property_obj, tenant_formset, resync=False)
    if meter_formset is not None:
        _save_meter_rows(property_obj, meter_formset, tenant_keys)
    resync_property(property_obj)
    return property_obj


@transaction.atomic
def save_tenants(property_obj, tenant_formset, share_unit):
    """The «Арендаторы» window: only the tenants and the share unit change."""
    property_obj.share_unit = share_unit
    if property_obj.is_owner_used and tenant_formset.active_forms():
        property_obj.occupancy = Property.Occupancy.TENANTS  # tenants added: no longer the landlord's own use
    property_obj.save(update_fields=['share_unit', 'occupancy'])
    _save_tenant_rows(property_obj, tenant_formset)
    return property_obj


def free_meters(tenant):
    """A tenant moves out: their meters stay on the object as free ones (the owner pays by them)."""
    tenant.meters.update(tenant=None, vacant=True)


def _save_tenant_rows(property_obj, tenant_formset, resync=True):
    """Save the tenant rows. Returns {key: tenant id}: «pk:<id>» of every kept tenant and
    «new:<form index>» of every row — the keys the meter rows name their tenant by."""
    keys = {}
    for index, tenant_form in enumerate(tenant_formset.forms):
        tenant = tenant_form.instance
        if tenant_form in tenant_formset.deleted_forms:
            if tenant.pk:
                free_meters(tenant)
                tenant.delete()
            continue
        if not (tenant.pk or tenant_form.has_changed()):
            continue  # untouched empty row
        tenant = tenant_form.save(commit=False)
        tenant.property = property_obj
        apply_share(tenant, tenant_form.cleaned_data['share'], property_obj.share_unit, property_obj.area)
        tenant.save()
        keys[f'new:{index}'] = keys[f'pk:{tenant.pk}'] = tenant.pk
    if resync:
        resync_property(property_obj)  # tenants changed: the services' layouts follow
    return keys


def _save_meter_rows(property_obj, meter_formset, tenant_keys):
    """Save the object's meters. Who pays by each comes from the tenant windows (`owner`):
    a kept tenant; a tenant who moved out — the meter is free; nobody — a common meter."""
    for meter_form in meter_formset.forms:
        meter = meter_form.instance
        if meter_form in meter_formset.deleted_forms:
            if meter.pk:
                meter.delete()
            continue
        meter = meter_form.save(commit=False)
        meter.property = property_obj
        owner = meter_form.cleaned_data.get('owner') or ''
        meter.tenant_id = None if property_obj.is_owner_used else tenant_keys.get(owner)
        meter.vacant = (not property_obj.is_owner_used and meter.tenant_id is None
                        and (owner == 'free' or owner.startswith(('pk:', 'new:'))))
        meter.save()
