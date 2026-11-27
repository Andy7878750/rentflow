"""Business logic for receipts (квитанции) and meters.

Two parts: the one-time setup of an object's receipts, and the monthly input
(amounts, tariffs, readings) with the split between tenants.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import models, transaction

from .models import (FormulaValue, Meter, MonthlyAmount, PayBundle, Payment, Reading, Receipt, ReceiptTariff,
                     IssuedBill, ServiceTemplate, TenantCoefficient)

# Sensible defaults for each ready-made receipt, so the lazy landlord mostly just confirms.
_BY_OWN_METERS = {'metered': True, 'layout': Receipt.Layout.TENANTS, 'split': Receipt.Split.METERS}
PRESETS = {
    Receipt.Kind.MANAGEMENT: {'split': Receipt.Split.SHARES},
    Receipt.Kind.ELECTRICITY: {**_BY_OWN_METERS, 'unit': 'кВт·ч'},
    Receipt.Kind.WATER: {**_BY_OWN_METERS, 'unit': 'м³'},
    Receipt.Kind.HOT_WATER: {**_BY_OWN_METERS, 'unit': 'м³'},
    # Heating of hot water (Гкал) and sewage (= cold + hot) are simplified for now: by meters, in м³.
    Receipt.Kind.HOT_WATER_HEATING: {**_BY_OWN_METERS, 'unit': 'м³'},
    Receipt.Kind.SEWAGE: {**_BY_OWN_METERS, 'unit': 'м³'},
    Receipt.Kind.HEATING: {'split': Receipt.Split.AREA},
    Receipt.Kind.GAS: {**_BY_OWN_METERS, 'unit': 'м³'},
    Receipt.Kind.INTERNET: {'split': Receipt.Split.EQUAL, 'amount_mode': Receipt.AmountMode.FIXED},
    # Capital repair is usually the owner's own expense.
    Receipt.Kind.CAPITAL_REPAIR: {'split': Receipt.Split.OWNER},
    Receipt.Kind.GARBAGE: {'split': Receipt.Split.EQUAL},
    Receipt.Kind.CUSTOM: {'split': Receipt.Split.SHARES},
}

# Template tiles of «Новая услуга», in this order (2026-11-15: only these five + «Своя» and the owner's own tiles).
# The other kinds stay in the model for services made before.
OFFERED_KINDS = [
    Receipt.Kind.MANAGEMENT, Receipt.Kind.ELECTRICITY, Receipt.Kind.HOT_WATER, Receipt.Kind.WATER, Receipt.Kind.INTERNET,
]
# A template's name on its tile and as the service's name, where it differs from the kind's label.
TEMPLATE_NAMES = {Receipt.Kind.MANAGEMENT: 'Коммунальные услуги'}
TILE_NAMES = {Receipt.Kind.MANAGEMENT: 'Ком. услуги'}


def template_name(kind):
    """The name a new service of this template gets: «Коммунальные услуги», «Электричество»…"""
    kind = kind if kind in Receipt.Kind.values else Receipt.Kind.CUSTOM
    return TEMPLATE_NAMES.get(kind, Receipt.Kind(kind).label)


def new_receipt(property_obj, kind, template=None):
    """An unsaved receipt of the given kind with its defaults filled in; `template` — the owner's own tile."""
    if kind not in Receipt.Kind.values:
        kind = Receipt.Kind.CUSTOM
    if template is not None:
        kind = Receipt.Kind.CUSTOM
    receipt = Receipt(property=property_obj, kind=kind)
    receipt.name = '' if kind == Receipt.Kind.CUSTOM else template_name(kind)
    if template is not None:
        apply_template(receipt, template)
        if property_obj.is_owner_used:
            receipt.layout = Receipt.Layout.COMMON
            receipt.split = Receipt.Split.OWNER
        return receipt
    for field, value in PRESETS[kind].items():
        setattr(receipt, field, value)
    if property_obj.is_owner_used:
        receipt.layout = Receipt.Layout.COMMON
        receipt.split = Receipt.Split.OWNER
    return receipt


# Soft hyphens (U+00AD) in long words, so a narrow template tile breaks them with a dash instead of cutting them.
_TILE_BREAKS = {
    'Электричество': 'Электри­чество',
    'Водоотведение': 'Водо­отведение',
    'Капитальный': 'Капи­тальный',
    'Содержание': 'Содер­жание',
    'подогрев': 'подо­грев',
}


def tile_label(label):
    """A template's name with soft hyphens in its long words."""
    return ' '.join(_TILE_BREAKS.get(word, word) for word in label.split(' '))


def template_tiles(property_obj, selected):
    """Template tiles of «Новая услуга»: every ready-made kind, the picked one and the ones already added marked."""
    have = set(property_obj.receipts.values_list('kind', flat=True))
    return [
        {'kind': kind, 'label': tile_label(TILE_NAMES.get(kind, kind.label)), 'name': template_name(kind),
         'selected': kind == selected, 'added': kind in have}
        for kind in OFFERED_KINDS
    ]


# ---------------------------------------------------------------------------
# The owner's own tiles: a «Своя» service saved «как плашка»
# ---------------------------------------------------------------------------

def own_tiles(property_obj, selected=None):
    """The own tiles of THIS object (2026-11-16: a tile saved on one object isn't offered on the others — they keep the
    standard ones), the picked one and the ones this object has marked."""
    have = set(property_obj.receipts.filter(kind=Receipt.Kind.CUSTOM).values_list('name', flat=True))
    return [
        {'template': template, 'label': tile_label(template.name), 'name': template.name,
         'selected': selected is not None and template.pk == selected.pk, 'added': template.name in have}
        for template in ServiceTemplate.objects.filter(property=property_obj)
    ]


def owner_template(property_obj, pk):
    """The object's own tile by its id (from ?tpl=…); None if it is another object's or gone."""
    if not str(pk or '').isdigit():
        return None
    return ServiceTemplate.objects.filter(property=property_obj, pk=int(pk)).first()


def apply_template(receipt, template):
    """A new service from the owner's own tile: its name, supplier and how it is charged and split."""
    receipt.name = template.name
    receipt.provider = template.provider
    receipt.metered = template.metered
    receipt.amount_mode = template.amount_mode
    receipt.fixed_amount = template.fixed_amount
    receipt.split = template.split
    receipt.input_mode = template.input_mode
    receipt.layout = Receipt.Layout.COMMON
    if receipt.metered and receipt.split == Receipt.Split.METERS:
        receipt.layout = Receipt.Layout.TENANTS


def tile_of(receipt):
    """The owner's own tile with this service's name, if there is one (the switch «Сохранить как плашку»)."""
    if receipt.kind != Receipt.Kind.CUSTOM or not receipt.name:
        return None
    return ServiceTemplate.objects.filter(property=receipt.property, name=receipt.name).first()


def save_as_tile(receipt, keep):
    """«Сохранить как плашку» on: the object's tile with the service's name gets its settings (made if new);
    off: that tile goes. Only this object gets it. Meters and tariffs are the object's — not kept in a tile."""
    if receipt.kind != Receipt.Kind.CUSTOM:
        return None
    if not keep:
        ServiceTemplate.objects.filter(property=receipt.property, name=receipt.name).delete()
        return None
    template, _ = ServiceTemplate.objects.update_or_create(
        property=receipt.property, name=receipt.name,
        defaults={
            'owner': receipt.property.owner,
            'provider': receipt.provider, 'metered': receipt.metered, 'amount_mode': receipt.amount_mode,
            'fixed_amount': receipt.fixed_amount if receipt.amount_mode == Receipt.AmountMode.FIXED else None,
            'split': receipt.split, 'input_mode': receipt.input_mode,
        },
    )
    return template


def services_label(count):
    """«нет услуг», «1 услуга», «3 услуги», «5 услуг»."""
    if not count:
        return 'нет услуг'
    if count % 10 == 1 and count % 100 != 11:
        word = 'услуга'
    elif 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        word = 'услуги'
    else:
        word = 'услуг'
    return f'{count} {word}'


def missing_kinds(property_obj):
    """Ready-made receipts the object doesn't have yet (shown as «add» buttons)."""
    have = set(property_obj.receipts.values_list('kind', flat=True))
    return [kind for kind in OFFERED_KINDS if kind not in have]


def normalize(receipt):
    """Bring the choices into a consistent state before saving."""
    if receipt.property.is_owner_used:
        receipt.layout = Receipt.Layout.COMMON
    if not receipt.metered:
        receipt.unit = ''
        receipt.tariff = receipt.tariff_night = None
        receipt.zones = 1
        receipt.layout = Receipt.Layout.COMMON
        if receipt.split != Receipt.Split.USAGE:  # «По расходу» keeps «было / стало» or «расход»
            receipt.input_mode = Receipt.InputMode.READINGS
        if receipt.amount_mode == Receipt.AmountMode.FORMULA:
            if receipt.split == Receipt.Split.USAGE:
                receipt.split = Receipt.Split.SHARES  # the formula itself reads the meters
        elif receipt.split == Receipt.Split.METERS:
            receipt.split = Receipt.Split.SHARES
    else:
        # The amount follows the readings, so it can't be a fixed sum.
        receipt.amount_mode = Receipt.AmountMode.MONTHLY
        if not receipt.unit:
            receipt.unit = 'ед.'
        if receipt.zones != 2:
            receipt.zones = 1
            receipt.tariff_night = None
        # The tenants' own meters decide what each pays; one common meter is split like a sum.
        if receipt.layout != Receipt.Layout.COMMON:
            receipt.split = Receipt.Split.METERS
        elif receipt.split in (Receipt.Split.METERS, Receipt.Split.USAGE):
            receipt.split = Receipt.Split.SHARES  # «по расходу» is for a sum from the receipt, not for meters × tariff
    if receipt.amount_mode != Receipt.AmountMode.FIXED:
        receipt.fixed_amount = None
    if receipt.amount_mode != Receipt.AmountMode.RATE:
        receipt.rate = receipt.persons = receipt.volume = None
        receipt.rate_unit = ''
    else:
        if receipt.rate_base != Receipt.RateBase.PERSON:
            receipt.rate_base, receipt.persons = Receipt.RateBase.AREA, None
        if receipt.split in (Receipt.Split.USAGE, Receipt.Split.METERS):
            receipt.split = Receipt.Split.SHARES  # the sum is known from the tariff: «по расходу» makes no sense
        if (not receipt.rate_unit and receipt.rate_base == Receipt.RateBase.AREA
                and receipt.split in (Receipt.Split.SHARES, Receipt.Split.EQUAL)):
            receipt.split = Receipt.Split.AREA  # old window: a sum of the m² is split by the m² (or «Плачу сам»)
    if receipt.split != Receipt.Split.USAGE or receipt.night_weight == 1:
        receipt.night_weight = None  # only «по расходу» weighs the night; 1 is the same as empty
    if receipt.property.is_owner_used:
        receipt.split = Receipt.Split.OWNER
    return receipt


COMMON_METER = 'Общий счётчик'


def wanted_meters(receipt):
    """[tenant_id or None] — the meters the receipt's layout calls for (services saved from code)."""
    if not receipt.metered:
        return []
    tenants = [] if receipt.property.is_owner_used else list(receipt.property.tenants.all())
    if receipt.layout == Receipt.Layout.COMMON or not tenants:
        return [None]
    wanted = [None] if receipt.layout == Receipt.Layout.BOTH else []
    return wanted + [tenant.pk for tenant in tenants]


def sync_meters(receipt):
    """Keep the receipt's meters in line with its settings.

    «Общий на объект» → one common meter; «У каждого свой» → one per tenant; «Общий + у каждого
    свой» → both. Not metered → none. Meters belong to the object; the receipt only links to
    them. Existing ones are kept where possible, so their history survives an edit.
    Returns {tenant_id or None: Meter}.
    """
    wanted = wanted_meters(receipt)
    meters = list(receipt.meters.all())
    for meter in meters:
        if meter.tenant_id not in wanted:
            receipt.meters.remove(meter)
            drop_if_unused(meter)
    have = {meter.tenant_id for meter in meters}
    kind, name, unit = meter_default(receipt)
    for tenant_id in wanted:
        if tenant_id not in have:
            receipt.meters.add(Meter.objects.create(
                property=receipt.property, tenant_id=tenant_id, kind=kind, name=name, unit=unit))


# «Сколько счётчиков» in the service window: short answers for the switch.
LAYOUT_SHORT = [
    (Receipt.Layout.COMMON, 'Один общий'),
    (Receipt.Layout.TENANTS, 'У каждого свой'),
    (Receipt.Layout.BOTH, 'Общий + у каждого'),
]


def meters_label(count):
    """«1 счётчик», «2 счётчика», «5 счётчиков»."""
    if count % 10 == 1 and count % 100 != 11:
        word = 'счётчик'
    elif 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        word = 'счётчика'
    else:
        word = 'счётчиков'
    return f'{count} {word}'


# What a meter measures: the ready-made kinds of the «Что за счётчик» menu, with their units.
METER_KINDS = [
    (Receipt.Kind.ELECTRICITY, 'Электричество', 'кВт·ч'),
    (Receipt.Kind.WATER, 'Вода холодная', 'м³'),
    (Receipt.Kind.HOT_WATER, 'Вода горячая', 'м³'),
    (Receipt.Kind.GAS, 'Газ', 'м³'),
    (Receipt.Kind.HEATING, 'Отопление', 'Гкал'),
]
# The «Что меряет» menu offers only these (gas too since 2026-11-20); the rest — the owner's own names, and every own
# name is a group of its own (meter_kind_key «custom:<имя>»): a service «По счётчикам» takes one group.
MENU_METER_KINDS = {Receipt.Kind.ELECTRICITY, Receipt.Kind.WATER, Receipt.Kind.HOT_WATER, Receipt.Kind.GAS}
# The name of a meter nobody named — not offered in the menu as the owner's own variant.
DEFAULT_METER_NAME = 'Счётчик'
# Services whose meters are of another kind: sewage is counted on the water meters, etc.
METER_KIND_OF = {Receipt.Kind.SEWAGE: Receipt.Kind.WATER, Receipt.Kind.HOT_WATER_HEATING: Receipt.Kind.HOT_WATER}


def meter_default(receipt):
    """(kind, name, unit) of a new meter of the service: by its template when the menu has that kind,
    else the menu's first one — «Электричество»."""
    kind = METER_KIND_OF.get(receipt.kind, receipt.kind)
    menu = [entry for entry in METER_KINDS if entry[0] in MENU_METER_KINDS]
    return next((entry for entry in menu if entry[0] == kind), menu[0])


def meter_kind_options(property_obj):
    """The «Что за счётчик» menu: ready-made kinds, then the owner's own names used before."""
    options = [
        {'kind': kind, 'name': name, 'unit': unit} for kind, name, unit in METER_KINDS if kind in MENU_METER_KINDS
    ]
    own = (
        Meter.objects.filter(property__owner=property_obj.owner, kind=Receipt.Kind.CUSTOM)
        .exclude(name=DEFAULT_METER_NAME)
        .order_by('name').values_list('name', 'unit')
    )
    seen = set()
    for name, unit in own:
        if name not in seen:
            seen.add(name)
            options.append({'kind': Receipt.Kind.CUSTOM, 'name': name, 'unit': unit})
    return options


def meter_who_options(property_obj):
    """[(value, label)] of the «Чей» menu: the object itself, then each tenant."""
    tenants = [] if property_obj.is_owner_used else list(property_obj.tenants.all())
    return [('', 'Объект (общий)')] + [(str(tenant.pk), tenant.name) for tenant in tenants]


# Posted as lists, one value per row: meter_id, meter_kind, meter_name, …
METER_FIELDS = ['id', 'kind', 'name', 'who', 'serial', 'tariff', 'tariffn', 'unit', 'initial', 'initialn']


def _num(value):
    return fmt_number(value) if value is not None else ''


def new_meter_row(receipt):
    """An empty row («+ Добавить счётчик»): the service's kind, on the object."""
    kind, name, unit = meter_default(receipt)
    return {'id': '', 'kind': kind, 'name': name, 'who': '', 'serial': '',
            'tariff': '', 'tariffn': '', 'unit': unit, 'initial': '', 'initialn': ''}


def meter_rows(receipt, data=None):
    """Rows of «Счётчики» in the service window: what was posted, else the service's meters,
    else one meter by the service's template, on the object."""
    who_names = dict(meter_who_options(receipt.property))
    if data is not None and 'meter_kind' in data:
        lists = {key: data.getlist(f'meter_{key}') for key in METER_FIELDS}
        rows = [{key: (lists[key][i] if i < len(lists[key]) else '') for key in METER_FIELDS}
                for i in range(len(lists['kind']))]
    else:
        meters = list(receipt.meters.select_related('tenant')) if receipt.pk else []
        rows = [{
            'id': str(meter.pk), 'kind': meter.kind, 'name': meter.name,
            'who': str(meter.tenant_id or ''), 'serial': meter.serial,
            'tariff': _num(meter.tariff), 'tariffn': _num(meter.tariff_night), 'unit': meter.unit,
            'initial': _num(meter.initial), 'initialn': _num(meter.initial_night),
        } for meter in meters]
        if not rows:
            rows = [new_meter_row(receipt)]
    for row in rows:
        if row['who'] not in who_names:
            row['who'] = ''
        row['who_label'] = who_names[row['who']]
    return rows


def clean_meter(property_obj, row, tenant_ids=None):
    """One posted meter row → model values (an unknown tenant means the object's own meter)."""
    if tenant_ids is None:
        tenant_ids = {str(pk): pk for pk in property_obj.tenants.values_list('pk', flat=True)}
    kinds = {value for value, _, _ in METER_KINDS}
    meter_id = str(row.get('id') or '')
    return {
        'id': int(meter_id) if meter_id.isdigit() else None,
        'kind': row.get('kind') if row.get('kind') in kinds else Receipt.Kind.CUSTOM,
        'name': (row.get('name') or '').strip()[:100] or DEFAULT_METER_NAME,
        'tenant_id': None if property_obj.is_owner_used else tenant_ids.get(str(row.get('who') or '')),
        'serial': (row.get('serial') or '').strip()[:50],
        'tariff': parse_decimal(row.get('tariff')),
        'tariff_night': parse_decimal(row.get('tariffn')),
        'unit': (row.get('unit') or '').strip()[:20],
        'initial': parse_decimal(row.get('initial')),
        'initial_night': parse_decimal(row.get('initialn')),
    }


def parse_meters(property_obj, data):
    """The meter list posted from the service window, cleaned; None when the window sent none."""
    if 'meter_kind' not in data:
        return None
    tenant_ids = {str(pk): pk for pk in property_obj.tenants.values_list('pk', flat=True)}
    return [clean_meter(property_obj, row, tenant_ids) for row in meter_rows(Receipt(property=property_obj), data)]


def _store_meter(property_obj, values, meter=None):
    meter = meter or Meter(property=property_obj)
    for name, value in values.items():
        if name != 'id':
            setattr(meter, name, value)
    meter.save()
    return meter


@transaction.atomic
def save_meter(property_obj, row):
    """«✓» at the end of a meter row: the meter goes into the object's meters right away
    (a new service links to it when it is saved). Returns the meter."""
    values = clean_meter(property_obj, row)
    meter = property_obj.meters.filter(pk=values['id']).first() if values['id'] else None
    return _store_meter(property_obj, values, meter)


@transaction.atomic
def delete_meter(meter, keep_for=None):
    """«×» at the end of a meter row. The meter goes away with its readings, unless another
    service (other than keep_for, the one being edited) still counts by it — then it only
    leaves this service when the service is saved. Returns True when it was deleted."""
    others = meter.receipts.exclude(pk=keep_for) if keep_for else meter.receipts.all()
    if others.exists():
        return False
    meter.delete()
    return True


def layout_for(meters):
    """The service's layout follows its meters: only common ones, only tenants' ones, or both."""
    common = {meter['tenant_id'] is None for meter in meters}
    if common == {False}:
        return Receipt.Layout.TENANTS
    if common == {True, False}:
        return Receipt.Layout.BOTH
    return Receipt.Layout.COMMON


def save_meter_list(receipt, meters):
    """Make the service's meters exactly the posted list: update the known ones, add the new,
    unlink the removed (a meter no service uses goes away)."""
    existing = {meter.pk: meter for meter in receipt.meters.all()}
    kept = set()
    for values in meters:
        # Known to the service, or saved to the object with «✓» before the service was saved.
        meter = existing.get(values['id'])
        if meter is None and values['id']:
            meter = receipt.property.meters.filter(pk=values['id']).first()
        if receipt.zones != 2:
            values = {**values, 'tariff_night': None, 'initial_night': None}
        meter = _store_meter(receipt.property, values, meter)
        if meter.pk not in existing:
            receipt.meters.add(meter)
        kept.add(meter.pk)
    for pk, meter in existing.items():
        if pk not in kept:
            receipt.meters.remove(meter)
            drop_if_unused(meter)


def first_of_month(day):
    return day.replace(day=1)


# ---------------------------------------------------------------------------
# «Счётчик: Да» in the service window: the object's meters ticked, a tariff per kind of them
# ---------------------------------------------------------------------------

# Months before a service's first tariff change: its tariff applies «from always».
SINCE_ALWAYS = date(2000, 1, 1)
# Services with one price for all their meters: sewage is counted on cold and hot water at one rate.
ONE_TARIFF_KINDS = {Receipt.Kind.SEWAGE}
READY_METER_KINDS = {value for value, _, _ in METER_KINDS}
# Which of the object's meters a template ticks by itself.
TEMPLATE_METERS = {
    Receipt.Kind.ELECTRICITY: {Receipt.Kind.ELECTRICITY},
    Receipt.Kind.WATER: {Receipt.Kind.WATER},
    Receipt.Kind.HOT_WATER: {Receipt.Kind.HOT_WATER},
    Receipt.Kind.HOT_WATER_HEATING: {Receipt.Kind.HOT_WATER},
    Receipt.Kind.SEWAGE: {Receipt.Kind.WATER, Receipt.Kind.HOT_WATER},
    Receipt.Kind.HEATING: {Receipt.Kind.HEATING},
    Receipt.Kind.GAS: {Receipt.Kind.GAS},
}


def tariff_key(receipt, meter):
    """Which tariff of the service a meter counts by: its own (2026-11-13: a tariff per meter, typed in its row
    of the service window); «*» for one price for all (sewage)."""
    if receipt.kind in ONE_TARIFF_KINDS:
        return '*'
    return f'm:{meter.pk}'


def kind_key(receipt, meter):
    """The older key — one tariff per kind of meter (its kind, or «custom:<name>» for an own kind)."""
    if receipt.kind in ONE_TARIFF_KINDS:
        return '*'
    return meter.kind if meter.kind in READY_METER_KINDS else f'custom:{meter.name}'


def for_meter(by_key, receipt, meter, default=None):
    """The meter's own entry of a {key: …} dict, else the one of its kind (tariffs typed before 2026-11-13)."""
    found = by_key.get(tariff_key(receipt, meter))
    if found is None:
        found = by_key.get(kind_key(receipt, meter))
    return default if found is None else found


def meter_unit(meter):
    """The meter's unit; for a ready-made kind with none written — the usual one (кВт·ч, м³, Гкал)."""
    return meter.unit or next((unit for value, _, unit in METER_KINDS if value == meter.kind), '')


def tariff_label(key, meters):
    if key == '*':
        return 'Все отмеченные'
    return meters[0].name if meters else key


def tariff_at(rows, month):
    """The row in force in a month (rows of one key, oldest first); None before the first one."""
    current = None
    for row in rows:
        if row.valid_from <= month:
            current = row
    return current


def meter_tariff_at(meter, month):
    """The meter's own tariff row in force in the month (MeterTariff, prefetched `tariff_history`); None — none yet."""
    rows = sorted(meter.tariff_history.all(), key=lambda row: row.valid_from)
    return tariff_at(rows, month) or None


def save_meter_tariff(meter, day, night, today=None):
    """The tariff typed in the meter's window: a change starts this month (earlier months keep theirs), a change in the
    same month corrects its row; the meter's first tariff counts from always. Empty — nothing changes."""
    from .models import MeterTariff

    if day is None:
        return
    night = night if meter.day_night else None
    this_month = first_of_month(today or date.today())
    rows = list(meter.tariff_history.order_by('valid_from'))
    now = tariff_at(rows, this_month)
    if now and now.tariff == day and now.tariff_night == night:
        return
    if now and now.valid_from == this_month:
        now.tariff, now.tariff_night = day, night
        now.save(update_fields=['tariff', 'tariff_night'])
        return
    has_past = meter.readings.filter(month__lt=this_month).exists()
    MeterTariff.objects.create(meter=meter, valid_from=this_month if (rows or has_past) else SINCE_ALWAYS,
                               tariff=day, tariff_night=night)


def meter_price(receipt, entry, meter):
    """(day, night) price of a meter in the entry's month: its own tariff (2026-11-19), else the service's for it
    (ReceiptTariff, before), else the meter's / the service's old field."""
    own = meter_tariff_at(meter, entry.month) if getattr(entry, 'month', None) else None
    if own is not None:
        return own.tariff, own.tariff_night
    row = for_meter(entry.kind_tariffs, receipt, meter)
    if row is not None:
        return row.tariff, row.tariff_night
    day = meter.tariff if meter.tariff is not None else entry.tariff
    night = meter.tariff_night if meter.tariff_night is not None else entry.tariff_night
    return day, night


def kind_tariffs(receipt, month):
    """{key: ReceiptTariff} in force in the month (uses the prefetched receipt.tariffs)."""
    by_key = {}
    for row in sorted(receipt.tariffs.all(), key=lambda r: r.valid_from):
        by_key.setdefault(row.key, []).append(row)
    found = {key: tariff_at(rows, month) for key, rows in by_key.items()}
    return {key: row for key, row in found.items() if row is not None}


def busy_meters(receipt):
    """{meter id: the other service that counts by it} — one meter, one service, one tariff (2026-11-15).
    A meter this service already has is never busy for it (services made before could share one)."""
    mine = set(receipt.meters.values_list('pk', flat=True)) if receipt.pk else set()
    busy = {}
    others = (Receipt.objects.filter(property=receipt.property).exclude(pk=receipt.pk)
              .exclude(amount_mode=Receipt.AmountMode.FORMULA)  # a formula only reads meters: it locks none
              .prefetch_related('meters', 'tariffs'))
    for other in others:
        for meter in other.meters.all():
            if meter.pk not in mine:
                busy.setdefault(meter.pk, other)
    return busy


def default_meter_ids(receipt):
    """Which free meters a new service has switched on (2026-11-15, the user's rule): a template — the meters of its
    kind (Электричество — every free light meter); the owner's own tile — the meters with its name, if there are;
    «Своя» and the rest — every free meter. All the others are listed too, switched off."""
    busy = busy_meters(receipt)
    free = [meter for meter in receipt.property.meters.all() if meter.pk not in busy]
    kinds = TEMPLATE_METERS.get(receipt.kind)
    if kinds:
        return [meter.pk for meter in free if meter.kind in kinds]
    named = [meter.pk for meter in free if receipt.name and meter.name == receipt.name]
    return named or [meter.pk for meter in free]


def parse_meter_ids(property_obj, posted, receipt=None):
    """The ticked meters of the service window; None when the window sent no list. A meter of another service
    can't be ticked (its row is locked)."""
    if posted is None or 'meters_shown' not in posted:
        return None
    own = set(property_obj.meters.values_list('pk', flat=True))
    busy = busy_meters(receipt) if receipt is not None else {}
    return [int(pk) for pk in posted.getlist('meter_ids') if pk.isdigit() and int(pk) in own and int(pk) not in busy]


def new_meter_ids(property_obj, posted, receipt):
    """Back in the service window after «+ Добавить счётчик объекта»: the meters added meanwhile (not in the
    posted `known_meters`) and free come ticked."""
    if posted is None or 'known_meters' not in posted:
        return []
    known = {int(pk) for pk in posted.get('known_meters', '').split(',') if pk.isdigit()}
    busy = busy_meters(receipt)
    return [pk for pk in property_obj.meters.values_list('pk', flat=True) if pk not in known and pk not in busy]


_MONTHS = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь',
           'ноябрь', 'декабрь']


def _last_reading_text(meter):
    """«339 / 228 · ноябрь 2026», «расход 50 · ноябрь 2026», or the start reading «старт 222» before any month."""
    for reading in sorted(meter.readings.all(), key=lambda r: r.month, reverse=True):
        when = f'{_MONTHS[reading.month.month - 1]} {reading.month.year}'
        if reading.current is not None:
            value = fmt_number(reading.current)
            if meter.day_night:
                value += ' / ' + (fmt_number(reading.current_night) if reading.current_night is not None else '—')
            return value, when
        if reading.usage is not None:
            value = 'расход ' + fmt_number(reading.usage)
            if meter.day_night and reading.usage_night is not None:
                value += ' / ' + fmt_number(reading.usage_night)
            return value, when
    if meter.initial is not None:
        value = fmt_number(meter.initial)
        if meter.day_night and meter.initial_night is not None:
            value += ' / ' + fmt_number(meter.initial_night)
        return value, 'старт'
    return '', ''


def meter_position(meter):
    """Where the meter's drum stands now (2026-11-27, the tile drawn as a meter): the last «стало», or the start plus
    every «расход» typed after it. (day, night) — night only for a day/night meter; (None, None) — nothing yet."""
    day, night = meter.initial, meter.initial_night
    for reading in sorted(meter.readings.all(), key=lambda r: r.month):
        if reading.current is not None:
            day, night = reading.current, reading.current_night
        elif reading.usage is not None:
            day = (day or Decimal('0')) + reading.usage
            if reading.usage_night is not None:
                night = (night or Decimal('0')) + reading.usage_night
    if day is None:
        return None, None
    night = (night if night is not None else Decimal('0')) if meter.day_night else None
    return day, night


def meter_table(owner):
    """«Все счётчики»: every meter of the owner's objects, grouped by object. Read-only — a row leads to the window
    where the meter is changed: its service (tariff, who pays) or, outside services, the object window."""
    from apps.properties.models import Property

    groups = []
    properties = (Property.objects.filter(owner=owner).order_by('name')
                  .prefetch_related('meters__tenant', 'meters__readings', 'meters__receipts__tariffs',
                                    'meters__tariff_history'))
    for property_obj in properties:
        rows = []
        for meter in property_obj.meters.all():
            service = next(iter(meter.receipts.all()), None)
            if meter.tenant_id:
                who, who_cls = meter.tenant.name, 'is-tenant'
            elif meter.vacant:
                who, who_cls = 'Собственник', 'is-free'
            else:
                who, who_cls = 'Общий', ''
            value, when = _last_reading_text(meter)
            rows.append({
                # Not in a service yet: «Новая услуга» opens with the matching tile and this meter switched on.
                'new_kind': meter.kind if meter.kind in OFFERED_KINDS else Receipt.Kind.CUSTOM,
                'meter': meter, 'kind': meter.kind if meter.kind in READY_METER_KINDS else 'custom',
                'who': who, 'who_cls': who_cls, 'service': service,
                'tariff': busy_tariff_text(service, meter) if service else '',
                'last': value, 'last_when': when, 'unit': meter_unit(meter),
                # «История» column (2026-11-25): how many months the meter has readings for
                'months': len({reading.month for reading in meter.readings.all()}),
            })
            months = rows[-1]['months']
            rows[-1]['months_label'] = f"{months} {_plural(months, ('месяц', 'месяца', 'месяцев'))}" if months else 'нет показаний'
        groups.append({'property': property_obj, 'rows': rows})
    return groups


def parse_day(text):
    """'17.11.2026' (or '2026-11-17') → date; anything else → None."""
    from datetime import datetime

    for pattern in ('%d.%m.%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime((text or '').strip(), pattern).date()
        except ValueError:
            continue
    return None


def _inherited_notes(owner, month):
    """{receipt id: (note, carry)} a month has without its own row: the latest earlier row's note when it was
    «переносить» (it comes by itself into the next months; a month with its own row decides for itself)."""
    from apps.properties.services import shift_month

    found = {}
    rows = (Payment.objects.filter(receipt__property__owner=owner, month__lt=month, month__gte=shift_month(month, -24))
            .order_by('month'))
    for row in rows:  # oldest first: a later row decides
        found[row.receipt_id] = (row.note, True) if row.note and row.note_carry else None
    return {pk: value for pk, value in found.items() if value}


def _month_tiles(owner, month):
    """Per object, per service NAME (same-name services of an object are one bill — the sums add up): the month's sum
    from the object page, paid or not, the note. Services paid with one receipt (`PayBundle`, 2026-11-25) are one
    tile — a «folder»: the sum of its parts, one check, one date; it stands where its first part stands.
    [{'property', 'tiles': [tile or folder]}]; a folder has `bundle` and `parts` (its tiles)."""
    from apps.properties.models import Property

    zero = Decimal('0.00')
    own = {payment.receipt_id: payment for payment in Payment.objects.filter(receipt__property__owner=owner, month=month)}
    inherited = _inherited_notes(owner, month)

    def note_of(pk):
        if pk in own:
            return own[pk].note, own[pk].note_carry
        return inherited.get(pk, ('', False))

    rows = []
    for property_obj in Property.objects.filter(owner=owner).order_by('name').prefetch_related('pay_bundles'):
        bundles = {bundle.pk: bundle for bundle in property_obj.pay_bundles.all()}
        groups = {}
        for entry in month_bill(property_obj, month).entries:
            groups.setdefault(entry.receipt.name, []).append(entry)
        tiles = []
        for name, entries in groups.items():
            sums = [entry.total for entry in entries if entry.total is not None]
            dates = [own[e.receipt.pk].paid_on for e in entries if e.receipt.pk in own and own[e.receipt.pk].paid_on]
            paid = len(dates) == len(entries)
            notes = [note_of(e.receipt.pk) for e in entries]
            note, carry = next((n for n in notes if n[0]), ('', False))
            tiles.append({
                'name': name, 'key': entries[0].receipt.pk, 'kind': entries[0].receipt.kind, 'property': property_obj,
                'amount': sum(sums, zero) if sums else None, 'partial': bool(sums) and len(sums) < len(entries),
                'state': 'paid' if paid else ('due' if sums else 'empty'), 'paid_on': max(dates) if paid else None,
                'note': note, 'carry': carry, 'bundle_id': entries[0].receipt.pay_bundle_id,
            })
        if tiles:
            rows.append({'property': property_obj, 'tiles': _fold(tiles, bundles)})
    return rows


def _fold(tiles, bundles):
    """The tiles of an object with each receipt's parts folded into one tile where its first part stands. A receipt
    left with one part (a service deleted) shows as that plain tile."""
    zero = Decimal('0.00')
    parts = {}
    for tile in tiles:
        if tile['bundle_id'] in bundles:
            parts.setdefault(tile['bundle_id'], []).append(tile)
    out, done = [], set()
    for tile in tiles:
        pk = tile['bundle_id']
        if pk not in parts or len(parts[pk]) < 2:
            out.append(tile)
            continue
        if pk in done:
            continue
        done.add(pk)
        inner = parts[pk]
        missing = sum(1 for part in inner if part['amount'] is None)
        paid = all(part['state'] == 'paid' for part in inner)
        note, carry = next(((part['note'], part['carry']) for part in inner if part['note']), ('', False))
        out.append({
            'bundle': bundles[pk], 'name': bundles[pk].name, 'parts': inner, 'property': tile['property'],
            'key': bundles[pk].pk, 'amount': sum((part['amount'] or zero for part in inner), zero),
            'missing': missing, 'partial': any(part['partial'] for part in inner),
            'state': 'empty' if missing else ('paid' if paid else 'due'),
            'paid_on': max(part['paid_on'] for part in inner) if paid else None, 'note': note, 'carry': carry,
        })
    return out


def payment_table(owner, month):
    """«Оплаты» (2026-11-25, the user's «плашки»): what the owner pays the providers this month — objects down, each
    with tiles of ITS services only (objects have different services: no columns, no empty «—»). A sum comes from the
    month's input of the object page by itself and stands «не оплачено» until marked. A receipt of several services is
    one tile (`_fold`). Over the list — last month's bills still not paid, marked right there."""
    from apps.properties.services import shift_month

    zero = Decimal('0.00')
    rows = _month_tiles(owner, month)
    totals = {'due': zero, 'paid': zero, 'left': zero, 'unpaid': 0, 'empty': 0}
    for row in rows:
        row['due'] = row['paid'] = row['left'] = zero
        for tile in row['tiles']:
            if tile['state'] == 'empty' and not tile.get('parts'):
                totals['empty'] += 1
                continue
            if tile['state'] == 'empty':  # a receipt with a part not typed yet: the typed parts still count
                totals['empty'] += tile['missing']
            row['due'] += tile['amount']
            if tile['state'] == 'paid':
                row['paid'] += tile['amount']
            else:
                row['left'] += tile['amount']
                if tile['state'] == 'due':  # a receipt waiting for a sum is not «не оплачено» yet
                    totals['unpaid'] += 1
        for key in ('due', 'paid', 'left'):
            totals[key] += row[key]
    prev_month = shift_month(month, -1)
    prev = [tile for row in _month_tiles(owner, prev_month) for tile in row['tiles'] if tile['state'] == 'due']
    return {
        'rows': rows, 'totals': totals,
        'prev': prev, 'prev_month': prev_month, 'prev_left': sum((tile['amount'] for tile in prev), zero),
    }


def _payment_rows(receipt, month):
    """The month's mark rows of a service and of the object's other services with the same name (one bill); a new row
    starts with the note it inherits, so marking a month paid doesn't cut a carried note off."""
    inherited = _inherited_notes(receipt.property.owner, month)
    for one in receipt.property.receipts.filter(name=receipt.name):
        row = Payment.objects.filter(receipt=one, month=month).first()
        if row is None:
            note, carry = inherited.get(one.pk, ('', False))
            row = Payment(receipt=one, month=month, note=note, note_carry=carry)
        yield row


def save_payment(receipt, month, paid_on=None):
    """A tile of «Оплаты» paid on a date, or not paid (None)."""
    for row in _payment_rows(receipt, month):
        row.paid_on = paid_on
        row.save()


def save_payment_note(receipt, month, note, carry=False):
    """The note of a tile and «Переносить на следующий месяц»; an empty note carries nothing."""
    note = (note or '').strip()[:120]
    for row in _payment_rows(receipt, month):
        row.note, row.note_carry = note, bool(note and carry)
        row.save()


# ---------- «Оплаты»: receipts of several services — folders made by dragging (2026-11-25) ----------

def save_bundle_payment(bundle, month, paid_on=None):
    """The folder's check: every service of the receipt paid on one date, or none paid."""
    for receipt in bundle.parts.all():
        for row in _payment_rows(receipt, month):
            row.paid_on = paid_on
            row.save()


def save_bundle_note(bundle, month, note, carry=False):
    """The folder's «?»: the note goes on every service of it (each keeps it when taken out)."""
    for receipt in bundle.parts.all():
        save_payment_note(receipt, month, note, carry)


def _bundle_name(property_obj, name, bundle=None):
    """Two receipts of one object never share a name: «Квитанция», «Квитанция 2», …"""
    name = (name or '').strip()[:36] or 'Квитанция'
    taken = set(property_obj.pay_bundles.exclude(pk=getattr(bundle, 'pk', None)).values_list('name', flat=True))
    found, number = name, 2
    while found in taken:
        found = f'{name} {number}'
        number += 1
    return found


def _paid_on(receipts, month):
    """The date all the receipts are paid on in a month; None — not all paid."""
    dates = [Payment.objects.filter(receipt=receipt, month=month).values_list('paid_on', flat=True).first()
             for receipt in receipts]
    return max(dates) if dates and all(dates) else None


@transaction.atomic
def merge_tiles(property_obj, month, source, target):
    """A tile dragged onto another tile of the same object — as apps into a folder on a phone. `source` / `target`:
    a Receipt (a service, with its same-name twins) or a PayBundle (a receipt). Onto a service — a new receipt
    «Квитанция»; onto a receipt — the source joins it (a dragged receipt pours its parts in). One receipt — one date:
    the month's mark of the tile dropped ONTO goes to every part (2026-11-25, the user: «одна дата на все»).
    Returns (bundle, made_now)."""
    def receipts_of(item):
        if isinstance(item, PayBundle):
            return list(item.parts.all())
        return list(property_obj.receipts.filter(name=item.name))

    moving, landing = receipts_of(source), receipts_of(target)
    if not moving or not landing or {r.pk for r in moving} & {r.pk for r in landing}:
        raise ValueError('nothing to merge')
    paid_on = _paid_on(landing, month)
    if isinstance(source, PayBundle):
        source.delete()  # first: its name is free for the new one
    made = not isinstance(target, PayBundle)
    bundle = PayBundle.objects.create(property=property_obj, name=_bundle_name(property_obj, '')) if made else target
    for receipt in landing + moving:
        receipt.pay_bundle = bundle
        receipt.save(update_fields=['pay_bundle'])
    save_bundle_payment(bundle, month, paid_on)
    return bundle, made


def rename_bundle(bundle, name):
    bundle.name = _bundle_name(bundle.property, name, bundle)
    bundle.save(update_fields=['name'])


@transaction.atomic
def take_out(bundle, receipt):
    """«×» at a service in the receipt window: it is a tile of its own again (with its same-name twins). One service
    left — the receipt is gone."""
    bundle.parts.filter(name=receipt.name).update(pay_bundle=None)
    if bundle.parts.values('name').distinct().count() < 2:
        split_bundle(bundle)


def split_bundle(bundle):
    """«Разъединить»: every service a tile of its own again; the payment marks stay as they are."""
    bundle.parts.update(pay_bundle=None)
    bundle.delete()


def reorder_receipts(property_obj, ids):
    """The object's services in the order of `ids` (top to bottom on the object page); the ones not named keep
    their order after them. Other objects' ids are ignored."""
    receipts = list(property_obj.receipts.all())
    by_id = {receipt.pk: receipt for receipt in receipts}
    named = [by_id[pk] for pk in dict.fromkeys(ids) if pk in by_id]
    rest = [receipt for receipt in receipts if receipt not in named]
    for position, receipt in enumerate(named + rest, start=1):
        if receipt.position != position:
            receipt.position = position
            receipt.save(update_fields=['position'])


def _tariff_since(rows, month):
    """(«с ноября 2026» or '' for «from always», the tariff row before the one in force — or None)."""
    rows = sorted(rows, key=lambda row: row.valid_from)
    now = tariff_at(rows, month)
    if now is None:
        return '', None
    earlier = [row for row in rows if row.valid_from < now.valid_from]
    if now.valid_from == SINCE_ALWAYS:
        return '', None
    return f'с {_MONTHS_GEN[now.valid_from.month - 1]} {now.valid_from.year}', (earlier[-1] if earlier else None)


_MONTHS_GEN = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября',
               'ноября', 'декабря']


def tariff_table(owner, today=None):
    """«Услуги → Тарифы»: every tariff in force of the owner's services, grouped by object. Read-only — a tariff
    is changed where it lives (2026-11-23): a meter's — in its meter (the object window, `meter` in the row), the
    rest — in the service window. A row: the service · what the tariff is for
    (a meter, «за м²», a formula's «Тариф / норматив») · the price · since when · the price before."""
    from apps.properties.models import Property

    month = first_of_month(today or date.today())
    groups = []
    properties = (Property.objects.filter(owner=owner).order_by('name')
                  .prefetch_related('receipts__tariffs', 'receipts__meters__tariff_history', 'receipts__numbers'))
    for property_obj in properties:
        rows = []
        for receipt in property_obj.receipts.all():
            symbol = receipt.currency_symbol
            history = {}
            for row in receipt.tariffs.all():
                history.setdefault(row.key, []).append(row)

            def add(what, price, key_rows, kind='', note='', before_text=None, meter=None, key=''):
                since, before = _tariff_since(key_rows, month)
                ordered = sorted(key_rows, key=lambda row: row.valid_from)
                now = tariff_at(ordered, month)
                rows.append({
                    'receipt': receipt, 'meter': meter, 'what': what, 'kind': kind, 'note': note, 'price': price, 'since': since,
                    'before': before_text(before) if before is not None and before_text else '', 'key': key,
                    # «История» (2026-11-25): every price of this tariff, old to new; the one in force — «сейчас».
                    'history': [{'from': _tariff_since([row], row.valid_from)[0] or 'с начала', 'price': before_text(row),
                                 'now': row is now} for row in ordered if row.valid_from <= month] if before_text else [],
                })
                if not rows[-1]['history']:  # no rows of history yet — the price as it is, from the start
                    rows[-1]['history'] = [{'from': 'с начала', 'price': price, 'now': True}]
                count = len(rows[-1]['history'])
                rows[-1]['history_label'] = f"{count} {_plural(count, ('цена', 'цены', 'цен'))}"

            if receipt.amount_mode == Receipt.AmountMode.FORMULA:
                for number in receipt.numbers.all():
                    if number.monthly or number.value is None:
                        continue
                    unit = number_unit_text(number)
                    text = lambda value, unit=unit: f'{fmt_number(value)}{NBSP}{unit}'.strip()  # noqa: E731
                    key_rows = history.get(_number_key(number), [])
                    now = tariff_at(sorted(key_rows, key=lambda row: row.valid_from), month)
                    add(number.label, text(now.tariff if now else number.value), key_rows, note='в формуле',
                        before_text=lambda row, text=text: text(row.tariff), key=_number_key(number))
            elif receipt.amount_mode == Receipt.AmountMode.RATE:
                rate = rate_at(receipt, month)[0]
                if rate is not None:
                    per = rate_unit(receipt)
                    text = lambda value, per=per: f'{fmt_number(value)}{NBSP}{symbol}/{per}'  # noqa: E731
                    add(f'За {per}' if receipt.rate_unit else 'За человека' if per == 'чел.' else 'За м²', text(rate),
                        history.get(rate_key(receipt), []), before_text=lambda row, text=text: text(row.tariff),
                        key=rate_key(receipt))
            elif receipt.metered:
                seen = set()
                for meter in receipt.meters.all():
                    # The meter's own tariff first (2026-11-19), else the service's old one for it.
                    own_rows = list(meter.tariff_history.all())
                    key = f'meter:{meter.pk}' if own_rows else tariff_key(receipt, meter)
                    key_rows = own_rows or history.get(key) or history.get(kind_key(receipt, meter), [])
                    if key == '*' and key in seen:
                        continue
                    seen.add(key)
                    price = busy_tariff_text(receipt, meter)
                    if not price:
                        continue
                    unit = meter_unit(meter)

                    def before_text(row, meter=meter, unit=unit):
                        if meter.day_night:
                            night = fmt_number(row.tariff_night) if row.tariff_night is not None else '—'
                            return f'{fmt_number(row.tariff)} / {night} {symbol}'
                        return f'{fmt_number(row.tariff)} {symbol}' + (f'/{unit}' if unit else '')

                    what = 'Все счётчики' if key == '*' else meter.name + (f' № {meter.serial}' if meter.serial else '')
                    add(what, price, key_rows, kind=meter.kind if meter.kind in READY_METER_KINDS else 'custom',
                        note='день / ночь' if meter.day_night and key != '*' else '', before_text=before_text,
                        meter=None if key == '*' else meter, key=key)
        groups.append({'property': property_obj, 'rows': rows})
    return groups


def mixed_owners(meters, posted):
    """Both common meters and the tenants' own (or free) ones among the switched-on meters, by the «чей» just posted
    (who_<pk>; the meter's own when not posted). They go in separate services (2026-11-15): one service would
    take «the common minus the tenants'» across different things (water minus light)."""
    kinds = set()
    for meter in meters:
        name = f'who_{meter.pk}'
        value = posted.get(name, '') if posted is not None and name in posted else (
            str(meter.tenant_id) if meter.tenant_id else ('free' if meter.vacant else ''))
        kinds.add('common' if value == '' else 'own')
    return len(kinds) > 1


def busy_tariff_text(other, meter):
    """The tariff a locked meter counts by in its service: «45,50 ₽/кВт·ч», day / night «5,50 / 2,10 ₽»."""
    if by_usage(other):
        return 'делит по расходу'
    month = first_of_month(date.today())
    found = meter_tariff_at(meter, month) or for_meter(kind_tariffs(other, month), other, meter)
    day, night = (found.tariff, found.tariff_night) if found else (meter.tariff or other.tariff, meter.tariff_night or other.tariff_night)
    if day is None:
        return ''
    symbol = other.currency_symbol
    if meter.day_night:
        return f'{fmt_number(day)} / {fmt_number(night) if night is not None else "—"} {symbol}'
    unit = meter_unit(meter)
    return f'{fmt_number(day)} {symbol}' + (f'/{unit}' if unit else '')


def apply_meter_owners(property_obj, posted):
    """«Чей» of each meter row of the service window: '' — common, 'free' — the owner pays, a tenant's id —
    that tenant pays by it. Stored on the meter itself, so another service with the same meter sees it.
    Also «Было / стало | Расход» of each row (mode_<pk>) — how the meter's month is typed."""
    if posted is None:
        return
    tenants = {str(pk) for pk in property_obj.tenants.values_list('pk', flat=True)}
    modes = set(Receipt.InputMode.values)
    for meter in property_obj.meters.all():
        mode = posted.get(f'mode_{meter.pk}')
        if mode in modes and mode != meter.input_mode:
            meter.input_mode = mode
            meter.save(update_fields=['input_mode'])
        name = f'who_{meter.pk}'
        if name not in posted:
            continue
        value = posted.get(name, '')
        tenant_id = int(value) if value in tenants else None
        vacant = value == 'free'
        if meter.tenant_id != tenant_id or meter.vacant != vacant:
            meter.tenant_id, meter.vacant = tenant_id, vacant
            meter.save(update_fields=['tenant', 'vacant'])


def parse_tariffs(posted):
    """{key: (day, night)} typed in the tariff rows of the service window."""
    if posted is None:
        return {}
    keys, days, nights = (posted.getlist(name) for name in ('tariff_key', 'tariff_day', 'tariff_nightv'))
    return {
        key: (parse_decimal(days[i] if i < len(days) else ''), parse_decimal(nights[i] if i < len(nights) else ''))
        for i, key in enumerate(keys)
    }


def _meter_who(meter):
    if meter.tenant_id:
        return meter.tenant.name, 'is-tenant'
    if meter.vacant:
        return 'свободен', 'is-free'
    return 'общий', ''


def meter_picks(receipt, checked):
    """All the object's meters with a tick: kind (for the colour), name, №, start, whose. Every meter is listed
    (2026-11-15); which are switched on decides `checked` (default_meter_ids for a new service).
    `busy` — the other service that counts by the meter: its row is locked, shows that service's tariff
    and goes to the end of the list; free meters come first."""
    meters = list(receipt.property.meters.select_related('tenant'))
    busy = busy_meters(receipt)
    picks = []
    for meter in meters:
        who, who_cls = _meter_who(meter)
        start = ''
        if meter.initial is not None:
            start = fmt_number(meter.initial)
            if meter.day_night:
                start += ' / ' + (fmt_number(meter.initial_night) if meter.initial_night is not None else '—')
            start += f' {meter_unit(meter)}'.rstrip()
        picks.append({
            'meter': meter, 'checked': meter.pk in checked, 'key': tariff_key(receipt, meter),
            'kind': meter.kind if meter.kind in READY_METER_KINDS else 'custom',
            'who': who, 'who_cls': who_cls, 'start': start,
            'owner_key': 'common' if not meter.tenant_id and not meter.vacant else 'tenant',
            'shown': True,
            'who_value': str(meter.tenant_id) if meter.tenant_id else ('free' if meter.vacant else ''),
            'mode': meter_mode(receipt, meter),
            'busy': busy.get(meter.pk),
            'busy_tariff': busy_tariff_text(busy[meter.pk], meter) if meter.pk in busy else '',
        })
        if meter.pk in busy:
            picks[-1]['checked'] = False
    picks.sort(key=lambda pick: pick['busy'] is not None)  # stable: free first, then the locked ones
    return picks


def tariff_rows(receipt, picks, posted_tariffs=None, missing=()):
    """One tariff row per kind of the object's meters (rows of unticked kinds are hidden by app.js).
    Values: what was typed, else the tariff in force this month, else the meters' old own tariff."""
    current = kind_tariffs(receipt, first_of_month(date.today())) if receipt.pk else {}
    rows, order = {}, []
    for pick in picks:
        key = pick['key']
        if key not in rows:
            order.append(key)
            rows[key] = {'key': key, 'meters': [], 'used': False, 'night': False, 'unit': meter_unit(pick['meter'])}
        row = rows[key]
        row['meters'].append(pick['meter'])
        row['used'] = row['used'] or pick['checked']
        row['night'] = row['night'] or (pick['meter'].day_night and pick['checked'])
        row['any_night'] = row.get('any_night') or pick['meter'].day_night
    result = []
    for key in order:
        row = rows[key]
        if posted_tariffs is not None and key in posted_tariffs:
            day, night = posted_tariffs[key]
        elif for_meter(current, receipt, row['meters'][0]) is not None:
            found = for_meter(current, receipt, row['meters'][0])
            day, night = found.tariff, found.tariff_night
        else:
            legacy = next((m for m in row['meters'] if m.tariff is not None), None)
            day, night = (legacy.tariff, legacy.tariff_night) if legacy else (None, None)
        row.update({
            'label': tariff_label(key, row['meters']),
            'day': fmt_number(day) if isinstance(day, Decimal) else (day or ''),
            'night_value': fmt_number(night) if isinstance(night, Decimal) else (night or ''),
            'missing': key in missing,
        })
        result.append(row)
    return result


def missing_tariffs(receipt, meters, tariffs):
    """Keys of the ticked meters whose tariff is not typed (the night one too, for a day / night meter)."""
    missing = []
    for meter in meters:
        key = tariff_key(receipt, meter)
        day, night = for_meter(tariffs, receipt, meter, (None, None))
        if key not in missing and (day is None or (meter.day_night and night is None)):
            missing.append(key)
    return missing


def save_tariffs(receipt, tariffs, keys, today, fallbacks=None):
    """Store the typed tariffs of the ticked kinds. A changed one starts this month; earlier months keep theirs."""
    this_month = first_of_month(today)
    has_past = (
        Reading.objects.filter(meter__receipts=receipt, month__lt=this_month).exists()
        or receipt.monthly_amounts.filter(month__lt=this_month).exists()
    )
    for key in keys:
        day, night = tariffs.get(key, (None, None))
        if day is None:
            continue
        rows = list(receipt.tariffs.filter(key=key).order_by('valid_from'))
        now = tariff_at(rows, this_month)
        if now and now.tariff == day and now.tariff_night == night:
            continue
        fallback = (fallbacks or {}).get(key)
        if not rows and fallback is not None and fallback.tariff == day and fallback.tariff_night == night:
            continue
        if now and now.valid_from == this_month:
            now.tariff, now.tariff_night = day, night
            now.save(update_fields=['tariff', 'tariff_night'])
            continue
        # The first tariff of a new service counts from always; otherwise from this month.
        valid_from = this_month if (rows or has_past) else SINCE_ALWAYS
        ReceiptTariff.objects.create(receipt=receipt, key=key, valid_from=valid_from, tariff=day, tariff_night=night)


def link_meters(receipt, meter_ids, tariffs, today):
    """«Счётчик: Да» saved from the window: the service counts by the ticked meters of the object
    (they stay the object's — nothing is created or deleted), each kind by its tariff."""
    meters = list(receipt.property.meters.filter(pk__in=meter_ids))
    receipt.meters.set(meters)
    current = kind_tariffs(receipt, first_of_month(today))
    keys, typed, fallbacks = [], {}, {}
    for meter in meters:
        key = tariff_key(receipt, meter)
        if key not in keys:
            keys.append(key)
            typed[key] = for_meter(tariffs, receipt, meter, (None, None))
            fallbacks[key] = current.get(kind_key(receipt, meter))
    save_tariffs(receipt, typed, keys, today, fallbacks)


def keep_past_tariffs(receipt, old_tariff, old_tariff_night, today):
    """The tariff changed: months before the current one stay billed at the old one.

    Every past month that already has input (an amount row or readings) and no tariff of its
    own gets the old tariff written into it. The new tariff applies from this month on.
    """
    if old_tariff == receipt.tariff and old_tariff_night == receipt.tariff_night:
        return
    this_month = first_of_month(today)
    months = set(
        Reading.objects.filter(meter__receipts=receipt, month__lt=this_month).values_list('month', flat=True)
    )
    months |= set(receipt.monthly_amounts.filter(month__lt=this_month).values_list('month', flat=True))
    for month in months:
        row, _ = MonthlyAmount.objects.get_or_create(receipt=receipt, month=month)
        if row.tariff is None and row.tariff_night is None:
            row.tariff = old_tariff
            row.tariff_night = old_tariff_night
            row.save(update_fields=['tariff', 'tariff_night'])


def drop_if_unused(meter):
    """A meter no service uses any more goes away with its readings (as before the move to the object)."""
    if not meter.receipts.exists():
        meter.delete()


def release_free_meters(property_obj):
    """A meter no service counts by is the premises' common one (2026-11-16, the user's rule): the tenant is seated on
    a meter in a service, so when the service goes or switches the meter off, «чей» goes back to «Общий».
    A formula only reads a meter (2026-11-24): a meter only formulas have is free too — its readings are typed nowhere."""
    typed = Receipt.objects.filter(property=property_obj).exclude(amount_mode=Receipt.AmountMode.FORMULA)
    (Meter.objects.filter(property=property_obj).exclude(receipts__in=typed).exclude(tenant=None, vacant=False)
     .update(tenant=None, vacant=False))


def meter_readers(property_obj):
    """{meter id: [names of the formulas that read its usage]} — what breaks when the meter leaves its service."""
    from . import formula as fx

    readers = {}
    for receipt in property_obj.receipts.filter(amount_mode=Receipt.AmountMode.FORMULA).order_by('position', 'pk'):
        for block in fx.meter_blocks(receipt.formula or []):
            for pk in block['meters']:
                names = readers.setdefault(pk, [])
                if receipt.name not in names:
                    names.append(receipt.name)
    return readers


@transaction.atomic
def delete_receipt(receipt):
    """The service goes; the object's meters stay (they are the premises'), and those it alone counted by become common."""
    property_obj = receipt.property
    receipt.delete()
    release_free_meters(property_obj)


def _layout_of(meters):
    # A free meter (its tenant moved out) still counts as a tenant's one, not a common one; so does a common one divided
    # between the tenants by its own split (the service window, 2026-11-19): each meter is counted on its own.
    return layout_for([{'tenant_id': m.tenant_id or ('free' if m.vacant or m.split else None)} for m in meters])


@transaction.atomic
def save_receipt(receipt, formula=None, **options):
    """Save the service (_save_receipt), then the meters no service counts by any more become common.
    formula — the formula window's state (parse_formula) of a «Своя формула» service."""
    receipt = _save_receipt(receipt, **options)
    if receipt.amount_mode == Receipt.AmountMode.RATE:
        save_rate(receipt, options.get('today') or date.today())
    if is_formula(receipt) and formula is not None:
        save_formula(receipt, formula, options.get('today'))
    elif not is_formula(receipt) and receipt.formula:
        receipt.formula = []  # another way of charging: the formula goes (its numbers stay until it comes back)
        receipt.save(update_fields=['formula'])
    release_free_meters(receipt.property)
    return receipt


# ---------------------------------------------------------------------------
# «По площади»: a tariff × the object's area, or × the number of people (2026-11-16)
# ---------------------------------------------------------------------------

def rate_key(receipt):
    return f'rate:{receipt.rate_base}'


def save_rate(receipt, today):
    """Keep the tariff (and the people) with history: a change starts this month, earlier months keep theirs;
    a change in the same month corrects its row. The first one of a new service counts from always."""
    if receipt.rate is None:
        return
    this_month = first_of_month(today)
    key = rate_key(receipt)
    rows = list(receipt.tariffs.filter(key=key).order_by('valid_from'))
    now = tariff_at(rows, this_month)
    if now and now.tariff == receipt.rate and now.quantity == receipt.persons and now.volume == receipt.volume:
        return
    if now and now.valid_from == this_month:
        now.tariff, now.quantity, now.volume = receipt.rate, receipt.persons, receipt.volume
        now.save(update_fields=['tariff', 'quantity', 'volume'])
        return
    has_past = receipt.monthly_amounts.filter(month__lt=this_month).exists() or receipt.created_at.date() < this_month
    valid_from = this_month if (rows or has_past) else SINCE_ALWAYS
    ReceiptTariff.objects.create(receipt=receipt, key=key, valid_from=valid_from, tariff=receipt.rate,
                                 quantity=receipt.persons, volume=receipt.volume)


def rate_at(receipt, month):
    """(tariff, people, volume) in force in the month: from the history, else as the service says now."""
    rows = sorted((row for row in receipt.tariffs.all() if row.key == rate_key(receipt)), key=lambda row: row.valid_from)
    row = tariff_at(rows, month) or (rows[0] if rows else None)
    if row is None:
        return receipt.rate, receipt.persons, receipt.volume
    return row.tariff, row.quantity, row.volume


def rate_unit(receipt):
    """«По тарифу»: what the tariff is per — the unit chosen in the window, else by the old «за м² / за человека»."""
    return receipt.rate_unit or ('чел.' if receipt.rate_base == Receipt.RateBase.PERSON else 'м²')


def rate_total(receipt, month, typed=False):
    """(the month's sum, «45 м² × 7,12 ₽») of a «По тарифу» service; (None, why) while the area, the tariff
    or the volume are missing. typed — as the service window has it now (not saved yet), not from the history."""
    if typed or not receipt.pk:
        rate, persons, volume = receipt.rate, receipt.persons, receipt.volume
    else:
        rate, persons, volume = rate_at(receipt, month)
    symbol = receipt.currency_symbol
    if rate is None:
        return None, 'не указан тариф'
    if receipt.rate_unit:
        # The window of 2026-11-19: «Тариф ₽ за [ед.] × [объём]»; м² with no volume — the object's area.
        unit = receipt.rate_unit
        if volume is None and unit == 'м²':
            volume = receipt.property.area
            if not volume:
                return None, 'у объекта не указана площадь'
        if not volume:
            return None, 'не указан объём'
        return money(volume * rate), f'{fmt_number(volume)}{NBSP}{unit} × {fmt_number(rate)}{NBSP}{symbol}'
    if receipt.rate_base == Receipt.RateBase.PERSON:
        if not persons:
            return None, 'не указано, сколько человек'
        quantity, text = Decimal(persons), f'{persons}{NBSP}чел.'
    else:
        area = receipt.property.area
        if not area:
            return None, 'у объекта не указана площадь'
        quantity, text = area, f'{fmt_number(area)}{NBSP}м²'
    return money(quantity * rate), f'{text} × {fmt_number(rate)}{NBSP}{symbol}'


def _save_receipt(receipt, meters=None, today=None, excluded=None, keep_meters=False, meter_ids=None, tariffs=None):
    """Save the service. meters — the list from the service window (parse_meters); without it
    (saved from code) the meters follow the service's layout.
    meter_ids / tariffs — the window of «Счётчик: Да»: the object's meters ticked and a tariff per kind of them.
    keep_meters — the object's tenants changed: the service keeps the meters it has (they are the
    premises'; who pays by each is set on the object), only its layout follows them.
    excluded — tenants switched off in «Кто платит» (parse_excluded); None keeps them as they are."""
    today = today or date.today()
    if is_formula(receipt):
        # «Своя формула»: its meters are linked by save_formula (it only reads them) — never dropped here.
        normalize(receipt)
        receipt.save()
        if excluded is not None:
            receipt.excluded.set(excluded)
        return receipt
    if meter_ids is not None and by_usage(receipt):
        # «Делим по расходу»: the sum comes from the receipt; the ticked meters only give the proportion (no tariff).
        normalize(receipt)
        receipt.save()
        receipt.meters.set(receipt.property.meters.filter(pk__in=meter_ids))
        if excluded is not None:
            receipt.excluded.set(excluded)
        return receipt
    if meter_ids is not None:
        ticked = list(receipt.property.meters.filter(pk__in=meter_ids)) if receipt.metered else []
        if ticked and not receipt.property.is_owner_used:
            receipt.layout = _layout_of(ticked)
        receipt.zones = 2 if any(meter.day_night for meter in ticked) else 1
        if ticked:
            # The service keeps its first kind's tariff and unit too (shown on the object page as before).
            day, night = for_meter(tariffs or {}, receipt, ticked[0], (None, None))
            receipt.tariff, receipt.tariff_night, receipt.unit = day, night, meter_unit(ticked[0]) or receipt.unit
        normalize(receipt)
        receipt.save()
        if receipt.metered:
            link_meters(receipt, [meter.pk for meter in ticked], tariffs or {}, today)
        else:
            receipt.meters.clear()
        if excluded is not None:
            receipt.excluded.set(excluded)
        return receipt

    old = Receipt.objects.filter(pk=receipt.pk).values('tariff', 'tariff_night').first() if receipt.pk else None
    linked = list(receipt.meters.all()) if keep_meters and receipt.pk and receipt.metered else []
    if linked and not meters and not receipt.property.is_owner_used:
        meters = None
        receipt.layout = _layout_of(linked)
    if linked:
        # Day / night follows the meters (set in the object window).
        receipt.zones = 2 if any(meter.day_night for meter in linked) else receipt.zones
    if meters and receipt.metered and not receipt.property.is_owner_used:
        receipt.layout = layout_for(meters)
    normalize(receipt)
    receipt.save()
    if old and receipt.metered and not receipt.tariffs.exists():
        keep_past_tariffs(receipt, old['tariff'], old['tariff_night'], today)
    if meters and receipt.metered:
        save_meter_list(receipt, meters)
    elif not linked:
        sync_meters(receipt)
    if excluded is not None:
        receipt.excluded.set(excluded)
    return receipt


def split_warning(receipt):
    """A gentle note when the chosen split can't work yet with the object's data."""
    property_obj = receipt.property
    tenants = list(property_obj.tenants.all())
    if receipt.amount_mode == Receipt.AmountMode.RATE and receipt.rate_base == Receipt.RateBase.AREA and not property_obj.area:
        return 'Укажите площадь объекта в карточке объекта — по ней считается сумма.'
    if property_obj.is_owner_used or receipt.split == Receipt.Split.OWNER:
        return ''
    if not tenants:
        return 'У объекта пока нет арендаторов — до их добавления сумма остаётся на вас.'
    if receipt.split == Receipt.Split.AREA and (not property_obj.area or any(t.area is None for t in tenants)):
        return 'Чтобы делить по м², укажите площадь объекта и арендаторов в карточке объекта.'
    return ''


def resync_property(property_obj):
    """After the object's tenants or occupancy change, keep every receipt consistent."""
    for receipt in property_obj.receipts.all():
        save_receipt(receipt, keep_meters=True)
    release_free_meters(property_obj)  # also with no services at all


# ---------------------------------------------------------------------------
# Monthly input and the split between tenants
# ---------------------------------------------------------------------------

CENT = Decimal('0.01')
HUNDRED = Decimal('100')
NBSP = ' '


def money(value):
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def price_down(value):
    """A price counted from a receipt (sum ÷ usage, ÷ м², ÷ tenants) to kopecks, down (2026-11-25): qty × price never
    bills the tenants more than the receipt; the kopecks left over are the owner's."""
    return value.quantize(CENT, rounding=ROUND_DOWN)


def fmt_number(value, places=None):
    """Decimal('4200') → '4 200'; with places=2 → '4 200,00'. Russian separators."""
    if places is not None:
        value = value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
        text = f'{value:,.{places}f}'
    else:
        text = f'{value.normalize():,f}'
    return text.replace(',', NBSP).replace('.', ',')


def parse_decimal(text):
    """'4 200,50' → Decimal('4200.50'); empty or junk → None."""
    text = (text or '').replace(NBSP, '').replace(' ', '').replace(',', '.')
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


@dataclass
class Line:
    receipt: object
    amount: Decimal          # what the payer is billed
    formula: str
    base: Decimal = None     # the payer's part of the receipt itself, before the coefficient
    meter: object = None     # the meter the line is counted by, if any (shown under it in the bill)
    reading: object = None   # that meter's month: «было → стало» in the bill
    k: Decimal = Decimal('1')  # the coefficient the line was multiplied by (the service's × the tenant's)
    # The bill's table (2026-11-25, PDF «Услуга · Ед. · Кол-во · Тариф · Сумма»): amount = qty × price ÷ per,
    # the price in kopecks with the coefficient inside. None — no such columns (a formula, day / night).
    unit: str = ''
    qty: Decimal = None
    price: Decimal = None
    per: Decimal = Decimal('1')  # 100 — the qty is a percent
    qty_night: Decimal = None    # a day / night meter: «520 / 310» and «6,10 / 2,40» in one row (2026-11-25)
    price_night: Decimal = None

    def __post_init__(self):
        if self.base is None:
            self.base = self.amount


def tenant_coefficient(tenant, receipt):
    """The tenant's own coefficient for this service (2026-11-25, «Настроить счёт»): 1 unless «Коэффициент к услугам»
    is on. Read once per tenant object."""
    if tenant is None or not getattr(tenant, 'coef_on', False):
        return Decimal('1')
    cache = tenant.__dict__.get('_coefficients')
    if cache is None:
        cache = {c.receipt_id: c.value for c in TenantCoefficient.objects.filter(tenant=tenant)}
        tenant.__dict__['_coefficients'] = cache
    return cache.get(receipt.pk, Decimal('1'))


def tenant_line(receipt, exact, formula, tenant=None, cols=None):
    """A tenant's line: their exact part of the receipt, times the coefficient — the service's (old data, 1 now)
    and the tenant's own for this service.

    cols = (unit, qty, price, per) — «простое округление» (2026-11-25): the price to kopecks (× the coefficient, then
    to kopecks again), amount = qty × price ÷ per — what the tenant checks on a calculator; the exact part is not used
    and the kopecks left over stay with the owner (his rest is counted from `base`, the line without the coefficient)."""
    coefficient = receipt.coefficient * tenant_coefficient(tenant, receipt)
    text = formula if coefficient == 1 else f'{formula} × {fmt_number(coefficient)}'
    if cols is None:
        if coefficient == 1:
            return Line(receipt, money(exact), formula)
        return Line(receipt, money(exact * coefficient), text, base=money(exact), k=coefficient)
    unit, qty, price, per, *night = cols
    price = money(price)
    priced = price if coefficient == 1 else money(price * coefficient)
    amount, base = money(qty * priced / per), money(qty * price / per)
    qty_night = price_night = None
    if night:  # day / night: each zone qty × its tariff, the sum of both
        qty_night, price_night = night[0], money(night[1])
        price_night = price_night if coefficient == 1 else money(price_night * coefficient)
        amount += money(qty_night * price_night)
        base += money(qty_night * money(night[1]))
    return Line(receipt, amount, text, base=base, k=coefficient, unit=unit, qty=qty, price=priced, per=per,
                qty_night=qty_night, price_night=price_night)


_SPLIT_GROUP = {'shares': 'по долям', 'equal': 'поровну', 'area': 'по м²', 'usage': 'по расходу'}


def bill_groups(payer):
    """A payer's bill in two framed groups (variant А, 2026-11-17): «Общие» — sums split between the tenants,
    «По счётчикам» — what their own meters show. Lines keep the order of the service cards."""
    common, metered = [], []
    for line in payer.lines:
        receipt = line.receipt
        # «По расходу» (2026-11-23) — by the tenant's own meter too: «По счётчикам»
        (metered if receipt.metered or receipt.split in (Receipt.Split.METERS, Receipt.Split.USAGE) else common).append(line)
    groups = []
    if common:
        title = 'Общие'
        splits = {line.receipt.split for line in common}
        if payer.tenant is not None and len(splits) == 1:
            split = splits.pop()
            text = _SPLIT_GROUP.get(split, '')
            if split == Receipt.Split.SHARES and payer.tenant.share_percent is not None:
                text += f' {fmt_number(payer.tenant.share_percent)}%'
            if split == Receipt.Split.AREA and payer.tenant.area is not None:
                text += f' {fmt_number(payer.tenant.area)}{NBSP}м²'  # по м² — in м², not % (2026-11-20)
            if text:
                title += ' · ' + text
        groups.append({'title': title, 'lines': common, 'total': sum((line.amount for line in common), Decimal('0'))})
    if metered:
        groups.append({'title': 'По счётчикам', 'lines': metered,
                       'total': sum((line.amount for line in metered), Decimal('0'))})
    return groups


def bill_meter_rows(line):
    """Under a meter's line in the bill (2026-11-17, the user's fixes): «счётчик № 222», then one row per zone —
    «251 → 255 = 4 кВт·ч × 9,5 ₽ = 38,00 ₽» (day and night: «день …», «ночь …»; a meter typed as «Расход» — without
    the arrow). A coefficient other than 1 adds «× 1,2 = …»."""
    meter, reading, receipt = line.meter, line.reading, line.receipt
    if meter is None:
        return []
    rows = [f'счётчик №{NBSP}{meter.serial}' if meter.serial else 'счётчик']
    rows += getattr(reading, 'bill_rows', None) or [line.formula]
    if line.k != 1:
        rows.append(f'× {fmt_number(line.k)} = {fmt_number(line.amount, 2)}{NBSP}{receipt.currency_symbol}')
    return rows


def bill_vat(payer):
    """The VAT of a tenant's bill (2026-11-25, «Настроить счёт»): None — no VAT line (a plain bill, or «Без НДС»);
    else {'mode', 'rate' (as typed: «22», «8,1»), 'vat', 'net', 'pay'}: «в т. ч.» — the sum stays, the VAT is the part of it;
    «сверху» — the VAT is added to the sum. Kopecks ROUND_HALF_UP."""
    tenant = payer.tenant
    if tenant is None or not tenant.bill_requisites or tenant.vat == 'none':
        return None
    total, rate = payer.total, Decimal(tenant.vat_rate)
    if tenant.vat == 'in':
        vat = money(total * rate / (HUNDRED + rate))
        return {'mode': 'in', 'rate': fmt_number(rate.normalize()), 'vat': vat, 'net': total - vat, 'pay': total}
    vat = money(total * rate / HUNDRED)
    return {'mode': 'top', 'rate': fmt_number(rate.normalize()), 'vat': vat, 'net': total, 'pay': total + vat}


def bill_settings_state(tenant):
    """What the window «Счёт · арендатор» shows: the tenant's settings and a coefficient for every service of the
    object (the saved one, else 1)."""
    saved = {c.receipt_id: c.value for c in TenantCoefficient.objects.filter(tenant=tenant)}
    receipts = tenant.property.receipts.order_by('position', 'id')
    return {
        'coefficients': [{'receipt': r, 'value': saved.get(r.pk, Decimal('1'))} for r in receipts],
    }


def save_bill_settings(tenant, data):
    """Saves «Счёт · арендатор» (a POST QueryDict). Returns {field: message} — empty when saved.
    A plain bill keeps the typed requisites (switching back brings them back) but has no VAT."""
    errors = {}
    requisites = data.get('requisites') == '1'
    inn = ''.join(ch for ch in data.get('inn', '') if ch.isdigit())
    kpp = ''.join(ch for ch in data.get('kpp', '') if ch.isdigit())
    if requisites:
        if not data.get('legal_name', '').strip():
            errors['legal_name'] = 'Введите полное название.'
        if len(inn) not in (10, 12):
            errors['inn'] = 'ИНН — 10 цифр у организации, 12 — у ИП.'
        if kpp and len(kpp) != 9:
            errors['kpp'] = 'КПП — 9 цифр.'
    vat = data.get('vat') if requisites and data.get('vat') in ('none', 'in', 'top') else 'none'
    rate = parse_decimal(data.get('vat_rate') or '')
    if vat != 'none' and (rate is None or not Decimal('0') < rate < HUNDRED):
        errors['vat_rate'] = 'Ставка от 0 до 100 %.'
    due_on = data.get('due_on') == '1'
    try:
        due_day = int(data.get('due_day') or 0)
    except ValueError:
        due_day = 0
    if due_on and not 1 <= due_day <= 31:
        errors['due_day'] = 'Число от 1 до 31.'
    values = {}
    for key, raw in data.items():
        if key.startswith('k-') and key[2:].isdigit():
            value = parse_decimal(raw) if raw.strip() else Decimal('1')
            if value is None or not Decimal('0') < value < HUNDRED:
                errors[key] = 'От 0 до 100.'
            values[int(key[2:])] = value
    if errors:
        return errors
    tenant.bill_requisites = requisites
    tenant.legal_name = data.get('legal_name', '').strip()[:200]
    tenant.inn, tenant.kpp = inn[:12], kpp[:9]
    tenant.legal_address = data.get('legal_address', '').strip()[:250]
    tenant.vat = vat
    if rate is not None and Decimal('0') < rate < HUNDRED:
        tenant.vat_rate = rate
    tenant.due_on = due_on
    if due_on:
        tenant.due_day = due_day
    tenant.coef_on = data.get('coef_on') == '1'
    tenant.save()
    own = set(tenant.property.receipts.values_list('pk', flat=True))
    for receipt_id, value in values.items():
        if receipt_id not in own:
            continue
        if value == 1:
            TenantCoefficient.objects.filter(tenant=tenant, receipt_id=receipt_id).delete()
        else:
            TenantCoefficient.objects.update_or_create(tenant=tenant, receipt_id=receipt_id, defaults={'value': value})
    tenant.__dict__.pop('_coefficients', None)
    return {}


def bill_pay(payer):
    """«К оплате» of a payer's bill: with VAT on top when the tenant's bill has it."""
    vat = bill_vat(payer)
    return vat['pay'] if vat else payer.total


def bill_snapshot(payer):
    """The bill as it is given (2026-11-25): groups, lines with their rows under, VAT and «К оплате» — as text and
    numbers in strings, kept in IssuedBill.lines; bill_view reads it back."""
    vat = bill_vat(payer)
    return {
        'groups': [{'title': group['title'], 'lines': [
            {'name': line.receipt.name, 'amount': str(line.amount), 'rows': bill_meter_rows(line) or [line.formula]}
            for line in group['lines']]} for group in bill_groups(payer)],
        'vat': {key: str(value) for key, value in vat.items()} if vat else None,
        'pay': str(bill_pay(payer)),
    }


def bill_view(payer, issued=None):
    """What the bill on the object page shows — always the month counted now, changing as you type (2026-11-25, the
    user: «текущий»). `issued` — the newest version given for this month, only while it is exactly this bill (its №
    and date in the head); changed since — as if not issued: the next «PDF» makes a new version, no warnings.
    {'groups': [{'title', 'lines': [{'name', 'amount', 'rows'}]}], 'vat', 'pay', 'issued'}."""
    if issued is not None and issued.lines != bill_snapshot(payer):
        issued = None
    return {'groups': [{'title': g['title'], 'lines': [
                {'name': line.receipt.name, 'amount': line.amount, 'rows': bill_meter_rows(line) or [line.formula]}
                for line in g['lines']]} for g in bill_groups(payer)],
            'vat': bill_vat(payer), 'pay': bill_pay(payer), 'issued': issued}


def bill_number(tenant, month, day):
    """The number of a new version (2026-11-25): the day it is issued, «251126»; issued again that day for this tenant
    and month — «251126/1», «251126/2»."""
    base = day.strftime('%d%m%y')
    count = IssuedBill.objects.filter(tenant=tenant, month=month, issued_on=day).count()
    return base if not count else f'{base}/{count}'


def last_issued(tenant, month):
    """The newest version issued to the tenant for the month, or None."""
    return IssuedBill.objects.filter(tenant=tenant, month=month).defer('pdf').first()


@dataclass
class BillRow:
    """A tenant's bill of the month in «Счета»: the sum now, ready or what is missing, and the issued versions, the
    newest first (`issued` — the newest)."""

    property: object
    payer: object
    pay: Decimal
    ready: bool
    missing: str = ''
    versions: list = None

    @property
    def issued(self):
        return self.versions[0] if self.versions else None


def bill_rows(user, month):
    """Every tenant's bill of the month on the owner's objects, by object: [(property, [BillRow])]. A tenant with
    0 ₽ and «Остаётся на вас» are not here (2026-11-25); an issued one is, even if it is 0 ₽ now."""
    versions = {}
    for b in IssuedBill.objects.filter(property__owner=user, month=month).defer('pdf'):  # newest first
        versions.setdefault(b.tenant_id, []).append(b)
    out = []
    for property_obj in user.properties.order_by('name'):
        bill = month_bill(property_obj, month)
        missing = ', '.join(receipt.name for receipt in bill.missing)
        rows = []
        for payer in bill.payers:
            got = versions.get(payer.tenant.pk, [])
            pay = bill_pay(payer)
            if not pay and not got:
                continue
            rows.append(BillRow(property_obj, payer, pay, not bill.missing, missing and 'не введено: ' + missing, got))
        if rows:
            out.append((property_obj, rows))
    return out


def bill_file_name(title, month_label):
    """«Счёт ноябрь 2026 — Аптека Вита.pdf»: quotes and slashes out — they break file names."""
    clean = ''.join(ch for ch in title if ch not in '"«»\'/\\:*?<>|').strip() or 'счёт'
    return f'Счёт {month_label.lower()} — {clean}.pdf'


def bill_text(payer, title, month_label):
    """The bill as a message for WhatsApp / Telegram: lines with sums and «Итого»."""
    rows = [f'Счёт за {month_label.lower()} · {title}', '']
    for group in bill_groups(payer):
        for line in group['lines']:
            rows.append(f'{line.receipt.name}: {fmt_number(line.amount, 2)} ₽')
    rows += ['', f'Итого к оплате: {fmt_number(bill_pay(payer), 2)} ₽']  # with VAT on top, if any
    return '\n'.join(rows)


_UNITS = ('', 'один', 'два', 'три', 'четыре', 'пять', 'шесть', 'семь', 'восемь', 'девять', 'десять', 'одиннадцать',
          'двенадцать', 'тринадцать', 'четырнадцать', 'пятнадцать', 'шестнадцать', 'семнадцать', 'восемнадцать',
          'девятнадцать')
_TENS = ('', '', 'двадцать', 'тридцать', 'сорок', 'пятьдесят', 'шестьдесят', 'семьдесят', 'восемьдесят', 'девяносто')
_HUNDREDS = ('', 'сто', 'двести', 'триста', 'четыреста', 'пятьсот', 'шестьсот', 'семьсот', 'восемьсот', 'девятьсот')
# Word forms for 1 / 2–4 / 5+, and whether the scale is feminine (одна / две тысячи).
_SCALES = ((('рубль', 'рубля', 'рублей'), False), (('тысяча', 'тысячи', 'тысяч'), True),
           (('миллион', 'миллиона', 'миллионов'), False), (('миллиард', 'миллиарда', 'миллиардов'), False))


def _plural(n, forms):
    if n % 100 in range(11, 15):
        return forms[2]
    return forms[0] if n % 10 == 1 else forms[1] if n % 10 in (2, 3, 4) else forms[2]


def _triad(n, feminine):
    words = [_HUNDREDS[n // 100]]
    rest = n % 100
    if rest < 20:
        unit = _UNITS[rest]
    else:
        words.append(_TENS[rest // 10])
        unit = _UNITS[rest % 10]
    if feminine and unit in ('один', 'два'):
        unit = 'одна' if unit == 'один' else 'две'
    words.append(unit)
    return [word for word in words if word]


def money_words(amount):
    """A sum in words, as on a bill: 11705.80 → «Одиннадцать тысяч семьсот пять рублей 80 копеек»."""
    amount = money(Decimal(amount))
    negative = amount < 0
    amount = abs(amount)
    rubles = int(amount)
    kopecks = int((amount - rubles) * 100)
    words = []
    if rubles == 0:
        words = ['ноль']
    rest = rubles
    parts = []
    for forms, feminine in _SCALES:
        parts.append((rest % 1000, forms, feminine))
        rest //= 1000
    for index in range(len(parts) - 1, 0, -1):
        n, forms, feminine = parts[index]
        if n:
            words += _triad(n, feminine) + [_plural(n, forms)]
    words += _triad(parts[0][0], False)
    words.append(_plural(rubles, _SCALES[0][0]))
    text = ' '.join(words)
    if negative:
        text = 'минус ' + text
    return f'{text[0].upper()}{text[1:]} {kopecks:02d} {_plural(kopecks, ("копейка", "копейки", "копеек"))}'


@dataclass
class Payer:
    """A tenant (or the owner, when tenant is None) and what they pay this month."""

    tenant: object
    lines: list = field(default_factory=list)

    @property
    def total(self):
        return sum((line.amount for line in self.lines), Decimal('0'))


@dataclass
class MonthEntry:
    """One receipt as shown in the monthly input column."""

    receipt: object
    amount: object = None                        # MonthlyAmount or None
    tariff: object = None                        # effective tariff for metered receipts (day, if two)
    tariff_night: object = None
    readings: list = field(default_factory=list)  # [(meter, Reading)]
    total: object = None                         # the month's sum; None while input is missing
    kind_tariffs: dict = field(default_factory=dict)  # {key: ReceiptTariff} in force this month
    tariff_lines: list = field(default_factory=list)  # «Электричество 7,5 / 3,2 ₽ за кВт·ч» for the object page
    rate_text: str = ''                          # «По площади»: «45 м² × 7,12 ₽», or why it can't be counted
    month: object = None                         # the 1st of the month (the meters' own tariffs are taken at it)


@dataclass
class MonthBill:
    entries: list
    payers: list                                  # tenants, in order
    owner: Payer
    readings_done: int
    readings_total: int

    @property
    def to_invoice(self):
        return sum((payer.total for payer in self.payers), Decimal('0'))

    @property
    def missing(self):
        return [entry.receipt for entry in self.entries if entry.total is None]

    def payer_for(self, tenant_id):
        return next((payer for payer in self.payers if payer.tenant.pk == tenant_id), None)


def _readings_for(meters, month):
    """This month's reading for each meter.

    «Было» defaults to last month's «стало», and in the meter's first month to the starting
    reading typed in the service window. The same for the night part of day / night meters.
    """
    result = []
    for meter in meters:
        readings = list(meter.readings.all())
        reading = next((r for r in readings if r.month == month), None) or Reading(meter=meter, month=month)
        for prev, cur, initial in (('previous', 'current', 'initial'), ('previous_night', 'current_night', 'initial_night')):
            if getattr(reading, prev) is not None:
                continue
            earlier = [r for r in readings if r.month < month and getattr(r, cur) is not None]
            setattr(reading, prev, getattr(earlier[-1], cur) if earlier else getattr(meter, initial))
        # «Расход» services: last month's usage, shown at the end of the row until this month's is typed.
        for use, last in (('usage', 'last_usage'), ('usage_night', 'last_usage_night')):
            earlier = [r for r in readings if r.month < month and getattr(r, use) is not None]
            setattr(reading, last, getattr(earlier[-1], use) if earlier else None)
        # «Расход» meters: what the meter shows before this month — the last «стало» (or the start reading) plus every
        # usage typed after it (2026-11-23: «804 + расход», the next month adds on). None — can't be told.
        for counter, cur, use, initial in (('counter', 'current', 'usage', 'initial'),
                                           ('counter_night', 'current_night', 'usage_night', 'initial_night')):
            value = getattr(meter, initial)
            for r in sorted((r for r in readings if r.month < month), key=lambda r: r.month):
                if getattr(r, cur) is not None:
                    value = getattr(r, cur)
                elif getattr(r, use) is not None and value is not None:
                    value += getattr(r, use)
            setattr(reading, counter, value)
        result.append((meter, reading))
    return result


def meter_tariff_text(receipt, entry, meter):
    """The meter's tariff in the month, next to its №: «9,6 ₽/кВт·ч», day / night «5,5 / 2,1 ₽/кВт·ч», or ''."""
    day, night = meter_price(receipt, entry, meter)
    if day is None:
        return ''
    unit = meter_unit(meter) or receipt.unit
    price = fmt_number(day)
    if two_zones(receipt, meter):
        price += ' / ' + (fmt_number(night) if night is not None else '—')
    return f'{price}{NBSP}{receipt.currency_symbol}' + (f'/{unit}' if unit else '')


def meter_mode(receipt, meter):
    """How the meter's month is typed: its own choice («Было / стало» / «Расход»), else the service's (old data)."""
    return meter.input_mode or receipt.input_mode


def _raw_used(receipt, reading):
    if meter_mode(receipt, reading.meter) == Receipt.InputMode.USAGE:
        return reading.usage, reading.usage_night
    return reading.consumption, reading.consumption_night


def _negative(value):
    return value is not None and value < 0


def used(receipt, reading):
    """(day, night) usage of one meter's month: typed as is («Расход») or «стало − было» («Показания»).
    A negative one («стало» below «было», 2026-11-16) is a typo: it counts as not typed yet (the red dot stays)."""
    day, night = _raw_used(receipt, reading)
    return (None if _negative(day) else day), (None if _negative(night) else night)


def mark_negative(receipt, readings):
    """reading.bad / bad_night — the object page paints such a field red: «меньше «было»»."""
    for _, reading in readings:
        day, night = _raw_used(receipt, reading)
        reading.bad, reading.bad_night = _negative(day), _negative(night)


def by_usage(receipt):
    """«По квитанции / фиксированная» divided «По расходу» of the ticked meters."""
    return not receipt.metered and receipt.split == Receipt.Split.USAGE


def _usage_split(receipt, entry, payers, owner):
    """«По расходу»: the receipt's sum in proportion to each meter's usage this month (day + night).
    A tenant's meter → the tenant; a common or free one → the owner; the kopecks of rounding → the owner.
    Returns False while a reading is missing (the month isn't complete)."""
    # A night kWh weighs night_weight of a day one (night is cheaper); empty — the same (2026-11-16).
    weight = receipt.night_weight or Decimal('1')
    uses = []
    for meter, reading in entry.readings:
        day, night = used(receipt, reading)
        if day is None or (meter.two_zones and night is None):
            return False
        if not meter.two_zones:
            uses.append((meter, reading, day, None, day))
        else:
            uses.append((meter, reading, day, night, day + night * weight))
    total = entry.total
    whole = sum((use for *_, use in uses), Decimal('0'))
    currency = receipt.currency_symbol
    if not whole:
        owner.lines.append(Line(receipt, total, 'по счётчикам нет расхода'))
        return True
    unit = meter_unit(uses[0][0]) or 'ед.'
    billed = Decimal('0')
    price = price_down(total / whole)  # the price of a unit, to kopecks (2026-11-25, «простое округление»)
    # The price the bill uses (2026-11-25): «25 кВт·ч × 82,08 ₽» — it checks on a calculator. Day / night — each zone
    # its own qty × price, the same rows as «По счётчикам» («день 500 → 700 = 200 кВт·ч × 21,73 ₽ = …», «ночь …»);
    # PDF «200 / 90» · «21,73 / 21,73». A lighter night costs price × night_weight (down to kopecks).
    night_price = price_down(price * weight)
    for meter, reading, day, night, use in uses:
        exact = total * use / whole
        if night is None:
            formula = f'{fmt_number(day)}{NBSP}{unit} × {fmt_number(price)}{NBSP}{currency}'
            cols = (unit, day, price, Decimal('1'))
            own = money(day * price)
            reading.bill_rows = [_bill_row(receipt, meter, reading.previous, reading.current, day, price)]
        else:
            formula = (f'день {fmt_number(day)} {unit} × {fmt_number(price)}{NBSP}{currency} + '
                       f'ночь {fmt_number(night)} {unit} × {fmt_number(night_price)}{NBSP}{currency}')
            cols = (unit, day, price, Decimal('1'), night, night_price)
            own = money(day * price) + money(night * night_price)
            reading.bill_rows = [
                'день ' + _bill_row(receipt, meter, reading.previous, reading.current, day, price),
                'ночь ' + _bill_row(receipt, meter, reading.previous_night, reading.current_night, night, night_price)]
        payer = payers.get(meter.tenant_id) if meter.tenant_id else None
        if payer:
            line = tenant_line(receipt, exact, formula, payer.tenant, cols)
            line.meter, line.reading = meter, reading
            payer.lines.append(line)
        else:
            line = Line(receipt, own, formula + (' · свободный счётчик' if meter.vacant else ' · общий счётчик'))
            owner.lines.append(line)
        billed += line.base
    if total != billed:
        owner.lines.append(Line(receipt, total - billed, 'округление'))
    return True


def meter_payer_text(meter, tenants):
    """Who pays by the meter, for its row on the object page: the tenant, «Платите вы», or a common one divided, as it
    is divided: «Общий · Салон 45% · Кофе 55%», «Общий · по м² · Салон 120 м² · Кофе 80 м²», «Общий · поровну · Салон 1/3 ·
    Кофе 1/3 · вы 1/3» (whoever doesn't pay is left out; the owner's part — «вы …»)."""
    if meter.tenant_id:
        return meter.tenant.name
    if meter.vacant:
        return 'Платите вы'
    if not meter.split or not tenants:
        return 'Общий'
    off = {tenant.pk for tenant in meter.excluded.all()}
    paying = [tenant for tenant in tenants if tenant.pk not in off]
    if meter.split == Receipt.Split.EQUAL:
        if not off:
            return 'Общий · поровну'
        count = len(tenants) if meter.owner_takes else len(paying)
        parts = [f'{tenant.name} 1/{count}' for tenant in paying]
        if meter.owner_takes and paying:
            parts.append(f'вы {len(off)}/{count}')
        return 'Общий · поровну · ' + ' · '.join(parts)
    if meter.split == Receipt.Split.AREA:
        # the м² each pays for: its own while the owner takes the rest; the paying ones sharing it all — more each
        whole = tenants[0].property.area or sum((tenant.area or 0 for tenant in tenants), Decimal('0'))
        paid = sum((tenant.area or 0 for tenant in paying), Decimal('0'))
        scale = 1 if meter.owner_takes or not off or not paid else whole / paid
        parts = [f'{tenant.name} {fmt_number(((tenant.area or 0) * scale).quantize(Decimal("0.01")))}{NBSP}м²'
                 for tenant in paying]
        rest = whole - paid
        if meter.owner_takes and rest > 0:
            parts.append(f'вы {fmt_number(rest)}{NBSP}м²')
        return 'Общий · по м² · ' + ' · '.join(parts)
    lines = _split(Decimal('100'), Receipt(currency='RUB'), paying, tenants[0].property, all_tenants=tenants,
                   how=meter.split, owner_takes=meter.owner_takes)
    parts = [f'{tenant.name} {fmt_number(lines[tenant.pk].amount)}%' for tenant in paying if tenant.pk in lines]
    rest = Decimal('100') - sum((line.amount for line in lines.values()), Decimal('0'))
    if rest > 0:
        parts.append(f'вы {fmt_number(rest)}%')
    return 'Общий · ' + ' · '.join(parts)


def two_zones(receipt, meter):
    """Day and night: the meter is set so in the object window. The service's own «день / ночь» counts only for
    old services none of whose meters says it (2026-11-15: one day / night meter used to make all of them so)."""
    if meter.day_night:
        return True
    return receipt.zones == 2 and not any(m.day_night for m in receipt.meters.all())


def _bill_row(receipt, meter, previous, current, use, price):
    """The bill's row under a meter (2026-11-17): «251 → 255 = 4 кВт·ч × 9,5 ₽ = 38,00 ₽» — no «было / стало», no
    tariff apart; a meter typed as «Расход» — without the arrow. One for «По счётчикам» and «По расходу» (2026-11-25)."""
    unit, currency = meter_unit(meter) or receipt.unit, receipt.currency_symbol
    typed_usage = meter_mode(receipt, meter) == Receipt.InputMode.USAGE
    counted = '' if typed_usage else f'{fmt_number(previous)} → {fmt_number(current)} = '
    return (f'{counted}{fmt_number(use)}{NBSP}{unit} × {fmt_number(price)}{NBSP}{currency} = '
            f'{fmt_number(money(use * price), 2)}{NBSP}{currency}')


def _meter_cost(receipt, entry, reading):
    """(exact cost, formula) of one meter's month, or None while something is missing."""
    meter = reading.meter
    unit, currency = meter_unit(meter) or receipt.unit, receipt.currency_symbol
    tariff, tariff_night = meter_price(receipt, entry, meter)
    day, night = used(receipt, reading)
    if tariff is None or day is None:
        return None
    def bill_row(previous, current, use, price):
        return _bill_row(receipt, meter, previous, current, use, price)

    if not two_zones(receipt, meter):
        reading.bill_rows = [bill_row(reading.previous, reading.current, day, tariff)]
        formula = f'{fmt_number(day)} {unit} × {fmt_number(tariff)}{NBSP}{currency}'
        return day * tariff, formula
    if tariff_night is None or night is None:
        return None
    reading.bill_rows = ['день ' + bill_row(reading.previous, reading.current, day, tariff),
                         'ночь ' + bill_row(reading.previous_night, reading.current_night, night, tariff_night)]
    formula = (f'день {fmt_number(day)} {unit} × {fmt_number(tariff)}{NBSP}{currency} + '
               f'ночь {fmt_number(night)} {unit} × {fmt_number(tariff_night)}{NBSP}{currency}')
    return day * tariff + night * tariff_night, formula


def _split(total, receipt, tenants, property_obj, all_tenants=None, how=None, owner_takes=None, note=''):
    """Split a receipt's total between the paying tenants. Returns {tenant_id: Line}.

    all_tenants — everyone, the switched-off included. owner_takes (default — the service's «Остаётся на вас»):
    the part of those who don't pay stays with the owner; off — it is divided between those who pay (2026-11-19).
    how — the way to divide (default — the service's split); note — added after the formula («общий счётчик»)."""
    how = how or receipt.split
    owner_takes = receipt.owner_takes if owner_takes is None else owner_takes
    all_tenants = tenants if all_tenants is None else all_tenants
    someone_off = len(tenants) < len(all_tenants)
    pass_on = someone_off and not owner_takes and bool(tenants)  # the remainder goes to those who pay
    currency = receipt.currency_symbol
    total_text = f'{fmt_number(total, 2)}{NBSP}{currency}'
    tail = f' · {note}' if note else ''
    lines = {}
    if how == Receipt.Split.SHARES:
        base = sum((t.share_percent or Decimal('0') for t in tenants), Decimal('0')) if pass_on else HUNDRED
        for tenant in tenants if base else []:
            share = tenant.share_percent or Decimal('0')
            of = f' из {fmt_number(base)}%' if pass_on else ''
            cols = ('%', share, total, base) if not pass_on else ('%', share * HUNDRED / base, total, HUNDRED)
            lines[tenant.pk] = tenant_line(receipt, total * share / base, f'{total_text} × {fmt_number(share)}%{of}{tail}',
                                           tenant, cols)
    elif how == Receipt.Split.EQUAL and tenants:
        count = len(all_tenants) if someone_off and owner_takes else len(tenants)
        for tenant in tenants:
            lines[tenant.pk] = tenant_line(receipt, total / count, f'{total_text} ÷ {count}{tail}', tenant,
                                           ('доля', Decimal('1'), price_down(total / count), Decimal('1')))
    elif how == Receipt.Split.AREA and property_obj.area:
        base = sum((t.area or Decimal('0') for t in tenants), Decimal('0')) if pass_on else property_obj.area
        for tenant in tenants if base else []:
            area = tenant.area or Decimal('0')
            lines[tenant.pk] = tenant_line(
                receipt, total * area / base,
                f'{total_text} × {fmt_number(area)} из {fmt_number(base)}{NBSP}м²{tail}', tenant,
                ('м²', area, price_down(total / base), Decimal('1')),
            )
    return lines


def _common_meter(receipt, meter, exact, formula, tenants, payers, owner, property_obj):
    """A common meter of «По счётчикам» divided between the tenants (its own split, «не платит», «Остаётся на вас»);
    what is left — the owner's. Returns the meter's sum in kopecks (all of it is billed to someone)."""
    total = money(exact)
    off = {tenant.pk for tenant in meter.excluded.all()}
    paying = [tenant for tenant in tenants if tenant.pk not in off]
    lines = _split(total, receipt, paying, property_obj, all_tenants=tenants, how=meter.split,
                   owner_takes=meter.owner_takes, note=f'{_meter_title(meter).strip()} · общий')
    for tenant_id, line in lines.items():
        payers[tenant_id].lines.append(line)
    rest = total - sum((line.base for line in lines.values()), Decimal('0'))
    if rest:
        owner.lines.append(Line(receipt, rest, f'{formula} · общий счётчик, не распределено на арендаторов'))
    return total


@dataclass
class PayerPreview:
    """A tenant in «Кто платит» of the service window: the basis of their part and the sum, when known."""

    tenant: object
    basis: str
    amount_text: str = ''
    pays: bool = True


# Splits where a tenant can be switched off in «Кто платит»: by own meters each pays what the meter shows.
SWITCHABLE_SPLITS = (Receipt.Split.SHARES, Receipt.Split.EQUAL, Receipt.Split.AREA)


def excluded_ids(receipt):
    """Tenants switched off for this service («не платит»)."""
    return {tenant.pk for tenant in receipt.excluded.all()} if receipt.pk else set()


def parse_excluded(property_obj, posted):
    """The switches of «Кто платит»: every tenant whose switch is off. None — the block wasn't posted."""
    if posted is None or 'payers_shown' not in posted:
        return None
    paying = set(posted.getlist('pays'))
    return [tenant.pk for tenant in property_obj.tenants.all() if str(tenant.pk) not in paying]


def payer_preview(receipt, excluded=None):
    """«Кто платит» → «Арендаторы»: each tenant's basis (45%, ÷ 2, 30 м²) and, for a fixed sum,
    what they pay a month — the same split and rounding as month_bill. A sum that changes every
    month or comes from meters is not known yet, so only the basis is shown. excluded — tenants
    switched off (the posted form); without it, the saved ones."""
    property_obj = receipt.property
    tenants = list(property_obj.tenants.all())
    excluded = excluded_ids(receipt) if excluded is None else set(excluded)
    paying = [tenant for tenant in tenants if tenant.pk not in excluded]
    known = None
    if not receipt.metered and receipt.split != Receipt.Split.OWNER:
        if receipt.amount_mode == Receipt.AmountMode.FIXED:
            known = receipt.fixed_amount
        elif receipt.amount_mode == Receipt.AmountMode.RATE:
            known = rate_total(receipt, first_of_month(date.today()), typed=True)[0]
    lines = _split(known, receipt, paying, property_obj, all_tenants=tenants) if known else {}
    rows = []
    for tenant in tenants:
        pays = tenant.pk not in excluded
        if not pays:
            basis = ''
        elif receipt.split == Receipt.Split.EQUAL:
            basis = f'÷ {len(tenants) if len(paying) < len(tenants) and receipt.owner_takes else len(paying)}'
        elif receipt.split == Receipt.Split.AREA:
            basis = f'{fmt_number(tenant.area)}{NBSP}м²' if tenant.area is not None else '— м²'
        elif receipt.split == Receipt.Split.SHARES:
            basis = f'{fmt_number(tenant.share_percent or Decimal("0"))}%'
        elif receipt.split == Receipt.Split.USAGE:
            basis = 'по расходу'
        else:
            basis = ''
        line = lines.get(tenant.pk)
        rows.append(PayerPreview(tenant, basis, _rub(line.amount, receipt.currency_symbol) if line else '', pays))
    return rows


def _meter_title(meter):
    """«Электричество № 254569-251 » — a tariff line of the object page (a tariff is per meter now)."""
    return f'{meter.name} № {meter.serial} ' if meter.serial else f'{meter.name} '


def _tariff_lines(receipt, entry):
    """The month's tariffs of a metered service for the object page: one per kind of its meters."""
    currency = receipt.currency_symbol
    lines, seen = [], set()
    for meter, _ in entry.readings:
        key = tariff_key(receipt, meter)
        if key in seen:
            continue
        seen.add(key)
        day, night = meter_price(receipt, entry, meter)
        if day is None:
            lines.append(('' if key == '*' else _meter_title(meter), 'не указан'))
            continue
        price = fmt_number(day)
        if two_zones(receipt, meter):
            price = f'день {price} · ночь {fmt_number(night) if night is not None else "—"}'
        lines.append(('' if key == '*' else _meter_title(meter), f'{price}{NBSP}{currency} за {meter_unit(meter) or receipt.unit}'))
    # One kind: just the price; several: each with its name.
    return [text if len(lines) == 1 else name + text for name, text in lines]


def month_bill(property_obj, month):
    """Everything for the object page in one month: the input column and each payer's bill.

    Tenant amounts are rounded to kopecks and multiplied by the receipt's coefficient;
    whatever isn't billed to tenants — unoccupied shares, «Плачу сам», rounding — stays
    with the owner.
    """
    tenants = [] if property_obj.is_owner_used else list(property_obj.tenants.all())
    payers = {tenant.pk: Payer(tenant) for tenant in tenants}
    owner = Payer(None)
    entries = []
    readings_done = readings_total = 0

    prefetch = ('meters__readings', 'meters__tenant', 'meters__tariff_history', 'meters__excluded', 'monthly_amounts',
                'excluded', 'tariffs', 'numbers__values')
    for receipt in property_obj.receipts.prefetch_related(*prefetch):
        amount = next((a for a in receipt.monthly_amounts.all() if a.month == month), None)
        entry = MonthEntry(receipt=receipt, amount=amount, month=month)
        entries.append(entry)

        if receipt.metered:
            # A past month keeps the tariff it was billed at; otherwise the service's current one.
            if amount and (amount.tariff is not None or amount.tariff_night is not None):
                entry.tariff, entry.tariff_night = amount.tariff, amount.tariff_night
            else:
                entry.tariff, entry.tariff_night = receipt.tariff, receipt.tariff_night
            entry.kind_tariffs = kind_tariffs(receipt, month)
            entry.readings = _readings_for(receipt.meters.all(), month)
            for meter, _ in entry.readings:
                meter.two_zones = two_zones(receipt, meter)
                meter.mode = meter_mode(receipt, meter)
                meter.tariff_text = meter_tariff_text(receipt, entry, meter)
                meter.payer_text = meter_payer_text(meter, tenants)
                meter.icon_kind = meter.kind if meter.kind in READY_METER_KINDS else 'custom'
            # Meters of several kinds in one service (2026-11-19): each row with its own icon, the group neutral.
            entry.mixed = len({meter.icon_kind for meter, _ in entry.readings}) > 1
            mark_negative(receipt, entry.readings)
            entry.modes = {meter.mode for meter, _ in entry.readings}
            entry.all_usage = entry.modes == {Receipt.InputMode.USAGE}
            entry.some_usage = Receipt.InputMode.USAGE in entry.modes
            entry.tariff_lines = _tariff_lines(receipt, entry)
            costs = [(meter, _meter_cost(receipt, entry, reading)) for meter, reading in entry.readings]
            readings_total += len(costs)
            readings_done += sum(1 for _, cost in costs if cost is not None)
            if any(cost is None for _, cost in costs):
                continue
            if receipt.split == Receipt.Split.METERS:
                # Each tenant pays for what their own meter shows.
                common = None
                billed = Decimal('0')
                month_of = {meter.pk: reading for meter, reading in entry.readings}
                for meter, (exact, formula) in costs:
                    payer = payers.get(meter.tenant_id)
                    if meter.vacant and not meter.tenant_id:
                        # A free meter: its tenant moved out, the owner pays until a new one takes it.
                        line = Line(receipt, money(exact), f'{formula} · свободный счётчик')
                        owner.lines.append(line)
                        billed += line.base
                    elif meter.tenant_id is None and meter.split and tenants:
                        # A common meter of the service window (2026-11-19): its sum is divided like a receipt's.
                        billed += _common_meter(receipt, meter, exact, formula, tenants, payers, owner, property_obj)
                    elif meter.tenant_id is None and receipt.layout == Receipt.Layout.BOTH:
                        common = (common or Decimal('0')) + exact
                    elif payer:
                        reading = month_of.get(meter.pk)
                        tariff, tariff_night = meter_price(receipt, entry, meter)
                        day, night = used(receipt, reading)
                        cols = (meter_unit(meter) or receipt.unit, day, tariff, Decimal('1'))
                        if two_zones(receipt, meter):
                            cols += (night, tariff_night)
                        line = tenant_line(receipt, exact, formula, payer.tenant, cols)
                        line.meter, line.reading = meter, reading
                        payer.lines.append(line)
                        billed += line.base
                    else:
                        line = Line(receipt, money(exact), formula, meter=meter, reading=month_of.get(meter.pk))
                        owner.lines.append(line)
                        billed += line.base
                if common is None:
                    entry.total = billed
                else:
                    # The supplier bills the common meter; what the tenants' meters don't cover is the owner's.
                    entry.total = money(common)
                    if entry.total != billed:
                        owner.lines.append(Line(receipt, entry.total - billed, 'разница общего и счётчиков арендаторов'))
                continue
            entry.total = money(sum((cost[0] for _, cost in costs), Decimal('0')))
        elif receipt.amount_mode == Receipt.AmountMode.FORMULA:
            handled = _formula_month(receipt, entry, month, tenants, payers, owner)
            readings_total += len(entry.readings)
            readings_done += sum(1 for _, reading in entry.readings if used(receipt, reading)[0] is not None)
            if handled:
                continue  # each paid by his own meters, or the month isn't complete yet
        elif receipt.amount_mode == Receipt.AmountMode.FIXED:
            entry.total = receipt.fixed_amount
        elif receipt.amount_mode == Receipt.AmountMode.RATE:
            entry.total, entry.rate_text = rate_total(receipt, month)
        else:
            entry.total = amount.amount if amount else None

        if by_usage(receipt):
            entry.readings = _readings_for(receipt.meters.all(), month)
            for meter, _ in entry.readings:
                meter.two_zones = two_zones(receipt, meter)
                meter.mode = meter_mode(receipt, meter)
                meter.tariff_text = ''
                meter.payer_text = meter_payer_text(meter, tenants)
                meter.icon_kind = meter.kind if meter.kind in READY_METER_KINDS else 'custom'
            entry.mixed = len({meter.icon_kind for meter, _ in entry.readings}) > 1
            mark_negative(receipt, entry.readings)
            entry.modes = {meter.mode for meter, _ in entry.readings}
            entry.all_usage = entry.modes == {Receipt.InputMode.USAGE}
            entry.some_usage = Receipt.InputMode.USAGE in entry.modes
            readings_total += len(entry.readings)
            readings_done += sum(1 for _, reading in entry.readings if used(receipt, reading)[0] is not None)
            if entry.total is None or not entry.readings or not _usage_split(receipt, entry, payers, owner):
                entry.total = None  # the sum or a reading is still missing: the red dot stays
            continue
        if entry.total is None:
            continue
        # Tenants switched off in «Кто платит» don't pay: their part stays with the owner.
        excluded = excluded_ids(receipt)
        paying = [tenant for tenant in tenants if tenant.pk not in excluded]
        lines = {} if receipt.split == Receipt.Split.OWNER else _split(entry.total, receipt, paying, property_obj,
                                                                        all_tenants=tenants)
        for tenant_id, line in lines.items():
            payers[tenant_id].lines.append(line)
        # The owner's remainder is counted from the receipt itself, without the coefficient.
        rest = entry.total - sum((line.base for line in lines.values()), Decimal('0'))
        if rest:
            note = 'плачу сам' if receipt.split == Receipt.Split.OWNER else 'не распределено на арендаторов'
            owner.lines.append(Line(receipt, rest, note))

    return MonthBill(
        entries=entries,
        payers=list(payers.values()),
        owner=owner,
        readings_done=readings_done,
        readings_total=readings_total,
    )


@dataclass
class SumRow:
    """A number typed in by hand this month: a receipt's sum or a formula's «каждый месяц» number."""

    entry: object
    sub: str          # under the name: the provider, or what the number is
    field: str        # the posted name: amount-<receipt> / fnum-<number>
    value: object
    unit: str


@dataclass
class MonthInput:
    """The compact input page (2026-11-18): what to type this month, not the services one by one."""

    sums: list = field(default_factory=list)     # [SumRow]
    meters: list = field(default_factory=list)   # [(entry, [(meter, Reading)])] — each meter once
    auto: list = field(default_factory=list)     # [entry] counted by themselves: fixed, by area, formulas


def month_input(bill):
    """Regroup the month's entries for the compact page: sums to type, meter readings, the rest.
    A meter is shown once (one meter — one field), in the first service that takes its readings;
    a formula only reads meters, so it never shows them."""
    result = MonthInput()
    seen = set()

    def add_meters(entry):
        rows = [(meter, reading) for meter, reading in entry.readings if meter.pk not in seen]
        seen.update(meter.pk for meter, _ in rows)
        if rows:
            result.meters.append((entry, rows))

    for entry in bill.entries:
        receipt = entry.receipt
        if receipt.amount_mode == Receipt.AmountMode.FORMULA:
            numbers = getattr(entry, 'month_numbers', [])
            for number, value in numbers:
                result.sums.append(SumRow(entry, number.label, f'fnum-{number.pk}', value, number.unit))
            if not numbers:
                result.auto.append(entry)
            continue
        if receipt.metered:
            add_meters(entry)
            continue
        if receipt.amount_mode in (Receipt.AmountMode.FIXED, Receipt.AmountMode.RATE):
            result.auto.append(entry)
        else:
            amount = entry.amount.amount if entry.amount else None
            result.sums.append(SumRow(entry, receipt.provider, f'amount-{receipt.pk}', amount, receipt.currency_symbol))
        if by_usage(receipt):
            add_meters(entry)
    return result


@transaction.atomic
def save_month_input(property_obj, month, data):
    """Store the monthly input posted from the object page.

    Field names: amount-<receipt>, prev-<meter>, cur-<meter> (and prevn-/curn- for the night
    of day / night meters), use-<meter> / usen-<meter> for services that take the usage, and coef-<receipt> — the coefficient belongs to the receipt itself,
    not to the month. The tariff is set only in the service window. Only posted fields change;
    an emptied field clears the stored value.
    """
    for receipt in property_obj.receipts.prefetch_related('meters'):
        if f'coef-{receipt.pk}' in data:
            coefficient = parse_decimal(data.get(f'coef-{receipt.pk}'))
            if coefficient is None or coefficient <= 0 or coefficient >= 100:
                coefficient = Decimal('1')
            if coefficient != receipt.coefficient:
                receipt.coefficient = coefficient
                receipt.save(update_fields=['coefficient'])
        if f'amount-{receipt.pk}' in data:
            row, _ = MonthlyAmount.objects.get_or_create(receipt=receipt, month=month)
            row.amount = parse_decimal(data.get(f'amount-{receipt.pk}'))
            row.save(update_fields=['amount'])
        # «Своя формула»: its «Каждый месяц» numbers (fnum-<number>).
        for number in receipt.numbers.filter(monthly=True):
            if f'fnum-{number.pk}' in data:
                FormulaValue.objects.update_or_create(
                    number=number, month=month, defaults={'value': parse_decimal(data.get(f'fnum-{number.pk}'))})
        fields = {'prev': 'previous', 'cur': 'current', 'prevn': 'previous_night', 'curn': 'current_night',
                  'use': 'usage', 'usen': 'usage_night'}
        for meter in receipt.meters.all():
            posted = {name: f'{key}-{meter.pk}' for key, name in fields.items() if f'{key}-{meter.pk}' in data}
            if posted:
                reading, _ = Reading.objects.get_or_create(meter=meter, month=month)
                for name, key in posted.items():
                    setattr(reading, name, parse_decimal(data.get(key)))
                reading.save()


# ---------- «Формула» in the service window: an example of what a tenant will pay ----------

SAMPLE_SUM = Decimal('4200')        # a month's receipt, when the sum comes every month
SAMPLE_USE = Decimal('120')         # a meter's month (day)
SAMPLE_USE_NIGHT = Decimal('80')
SAMPLE_TARIFF = Decimal('5')
SAMPLE_TARIFF_NIGHT = Decimal('3')


@dataclass
class FormulaStep:
    """One line of the example: terms and operators, then «= result»."""

    items: list            # ('term', label, value) or ('op', sign)
    result: str


@dataclass
class FormulaExample:
    choices: list          # [(key, name)] — whom the example is for
    chosen: str
    payer: str             # «Виктор» or «Вы»
    amount: Decimal
    amount_text: str
    steps: list


def _rub(value, currency):
    return f'{fmt_number(value, 2)}{NBSP}{currency}'


def formula_example(receipt, chosen=None):
    """What the service's settings mean, on example numbers, for one tenant (or the owner).

    The same arithmetic as month_bill: kopecks ROUND_HALF_UP, the coefficient only on tenants.
    Typed tariffs and a fixed sum are used as they are; the usage and a monthly sum are samples.
    """
    property_obj = receipt.property
    currency, unit = receipt.currency_symbol, receipt.unit or 'ед.'
    tenants = [] if property_obj.is_owner_used else list(property_obj.tenants.all())
    choices = [(str(tenant.pk), tenant.name) for tenant in tenants]
    tenant = next((t for t in tenants if str(t.pk) == str(chosen)), tenants[0] if tenants else None)
    if receipt.split == Receipt.Split.OWNER:
        tenant = None
    steps = []

    def term(label, value):
        return ('term', label, value)

    def op(sign):
        return ('op', sign)

    def coefficient(items):
        k = receipt.coefficient * tenant_coefficient(tenant, receipt) if tenant else Decimal('1')
        if k != 1:
            items += [op('×'), term('Коэффициент', fmt_number(k))]

    if receipt.metered:
        tariff = receipt.tariff if receipt.tariff is not None else SAMPLE_TARIFF
        if receipt.zones == 2:
            night_tariff = receipt.tariff_night if receipt.tariff_night is not None else SAMPLE_TARIFF_NIGHT
            items = [term('Расход день', f'{fmt_number(SAMPLE_USE)} {unit}'), op('×'),
                     term('Тариф день', _rub(tariff, currency)), op('+'),
                     term('Расход ночь', f'{fmt_number(SAMPLE_USE_NIGHT)} {unit}'), op('×'),
                     term('Тариф ночь', _rub(night_tariff, currency))]
            exact = SAMPLE_USE * tariff + SAMPLE_USE_NIGHT * night_tariff
        else:
            items = [term('Расход', f'{fmt_number(SAMPLE_USE)} {unit}'), op('×'), term('Тариф', _rub(tariff, currency))]
            exact = SAMPLE_USE * tariff
        if receipt.split == Receipt.Split.METERS and tenant:
            # The tenant's own meter is their whole part.
            coefficient(items)
            amount = tenant_line(receipt, exact, '', tenant).amount
            steps.append(FormulaStep(items, _rub(amount, currency)))
            return FormulaExample(choices, str(tenant.pk), tenant.name, amount, _rub(amount, currency), steps)
        total = money(exact)
        steps.append(FormulaStep(items, _rub(total, currency)))
        total_label = 'Сумма по счётчику'
    else:
        fixed = receipt.amount_mode == Receipt.AmountMode.FIXED and receipt.fixed_amount
        total = receipt.fixed_amount if fixed else SAMPLE_SUM
        total_label = 'Сумма в месяц' if fixed else 'Сумма квитанции'

    total_term = term(total_label, _rub(total, currency))
    if tenant is None:
        if not steps:
            steps.append(FormulaStep([total_term], _rub(total, currency)))
        return FormulaExample(choices, '', 'Вы', total, _rub(total, currency), steps)

    if receipt.split == Receipt.Split.EQUAL:
        items = [total_term, op('÷'), term('Арендаторов', str(len(tenants)))]
        exact = total / len(tenants)
    elif receipt.split == Receipt.Split.AREA:
        area, whole = tenant.area or Decimal('0'), property_obj.area
        items = [total_term, op('×'), term('Площадь', f'{fmt_number(area)}{NBSP}м²'),
                 op('÷'), term('Площадь объекта', f'{fmt_number(whole)}{NBSP}м²' if whole else '—')]
        exact = total * area / whole if whole else Decimal('0')
    else:
        share = tenant.share_percent or Decimal('0')
        items = [total_term, op('×'), term('Доля', f'{fmt_number(share)}%')]
        exact = total * share / HUNDRED
    coefficient(items)
    amount = tenant_line(receipt, exact, '', tenant).amount
    steps.append(FormulaStep(items, _rub(amount, currency)))
    return FormulaExample(choices, str(tenant.pk), tenant.name, amount, _rub(amount, currency), steps)


# ---------------------------------------------------------------------------
# «Своя формула»: numbers, meters and signs (formula.py counts; 2026-11-16)
# ---------------------------------------------------------------------------

# Units of the formula's numbers (the window adds «свой вариант…»).
FORMULA_UNITS = ['₽', 'кВт·ч', 'м³', 'Гкал', 'м²', 'чел.']
# A «Тариф / норматив» this big is kept on the number only (no history row: ReceiptTariff holds up to 999 999,9999).
_HISTORY_LIMIT = Decimal('1000000')


def is_formula(receipt):
    return not receipt.metered and receipt.amount_mode == Receipt.AmountMode.FORMULA


def meter_kind_key(meter):
    """What a meter measures, as the formula's palette groups them: its kind, or «custom:<name>» for an own kind."""
    return meter.kind if meter.kind in READY_METER_KINDS else f'custom:{meter.name}'


def number_unit_text(number):
    """«₽/Гкал», «Гкал», ''."""
    if number.per:
        return f'{number.unit or ""}/{number.per}'
    return number.unit


def _number_key(number):
    return f'num:{number.pk}'


def save_number_value(number, today):
    """«Тариф / норматив» with history, as a tariff: a change starts this month, earlier months keep theirs."""
    if number.monthly or number.value is None or abs(number.value) >= _HISTORY_LIMIT:
        return
    receipt = number.receipt
    this_month = first_of_month(today)
    key = _number_key(number)
    rows = list(receipt.tariffs.filter(key=key).order_by('valid_from'))
    now = tariff_at(rows, this_month)
    if now and now.tariff == number.value:
        return
    if now and now.valid_from == this_month:
        now.tariff = number.value
        now.save(update_fields=['tariff'])
        return
    has_past = receipt.created_at.date() < this_month or receipt.monthly_amounts.filter(month__lt=this_month).exists()
    valid_from = this_month if (rows or has_past) else SINCE_ALWAYS
    ReceiptTariff.objects.create(receipt=receipt, key=key, valid_from=valid_from, tariff=number.value)


def number_at(number, month):
    """A «Тариф / норматив» in force in the month (uses the prefetched receipt.tariffs); a «Каждый месяц» number —
    what was typed for the month (prefetched number.values), or None."""
    if number.monthly:
        row = next((row for row in number.values.all() if row.month == month), None)
        return row.value if row else None
    rows = sorted((row for row in number.receipt.tariffs.all() if row.key == _number_key(number)),
                  key=lambda row: row.valid_from)
    row = tariff_at(rows, month) or (rows[0] if rows else None)
    return row.tariff if row is not None else number.value


def parse_formula(posted):
    """The formula window's state posted as JSON (`formula_json`): {numbers, blocks, owners}; None — not posted."""
    import json

    if posted is None or 'formula_json' not in posted:
        return None
    try:
        data = json.loads(posted.get('formula_json') or '{}')
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def _clean_unit(text):
    """A unit as typed; «-», «—» (typed for «no unit», a coefficient) — no unit, not a unit of its own."""
    unit = str(text or '').strip()[:12]
    return '' if not unit.strip('-–—_. ') else unit


def _clean_numbers(raw):
    """The posted numbers: [{key, label, monthly, unit, per, value}] — key is the stored id or a new one («n3»)."""
    numbers = []
    for position, item in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(item, dict):
            continue
        monthly = bool(item.get('monthly'))
        raw_value = item.get('value')
        value = None if monthly or raw_value is None else parse_decimal(str(raw_value))
        numbers.append({
            'key': str(item.get('id', '')),
            'label': str(item.get('label') or '').strip()[:60] or f'Число {position + 1}',
            'monthly': monthly,
            'unit': _clean_unit(item.get('unit')),
            'per': '' if monthly else _clean_unit(item.get('per')),
            'value': value,
        })
    return numbers


def _posted_owner(value, tenant_ids):
    """«Чей» posted for a meter: (tenant id or None, vacant)."""
    value = str(value if value is not None else '')
    if value.isdigit() and int(value) in tenant_ids:
        return int(value), False
    return None, value == 'free'


def formula_owners(property_obj, data, receipt=None):
    """{meter id: tenant id or None} — as the formula window has it now: the posted «чей» of meters it may change,
    the stored one of meters another service («По счётчикам») seats tenants on."""
    tenant_ids = set(property_obj.tenants.values_list('pk', flat=True))
    busy = busy_meters(receipt) if receipt is not None else {}
    posted = (data or {}).get('owners') or {}
    owners = {}
    for meter in property_obj.meters.all():
        if str(meter.pk) in posted and meter.pk not in busy:
            owners[meter.pk] = _posted_owner(posted[str(meter.pk)], tenant_ids)[0]
        else:
            owners[meter.pk] = meter.tenant_id
    return owners


def _posted_blocks(data, number_keys, meter_ids):
    """The posted blocks with number keys («12», «n3») as they are — for checking before anything is saved."""
    from . import formula as fx

    raw = []
    for block in (data or {}).get('blocks') or []:
        if isinstance(block, dict) and block.get('t') == 'num':
            key = str(block.get('id', ''))
            if key in number_keys:
                raw.append({'t': 'num', 'id': key})
        else:
            raw.append(block)
    return fx.clean_blocks(raw, set(number_keys), meter_ids)


def typed_meters(property_obj):
    """{meter id: [names of the services its readings are typed in]} — services that aren't formulas («По счётчикам»,
    «Делим по расходу»). Only these meters can go in a formula: one meter — one field (2026-11-16)."""
    typed = {}
    rows = (Receipt.objects.filter(property=property_obj, meters__isnull=False)
            .exclude(amount_mode=Receipt.AmountMode.FORMULA).values_list('meters', 'name'))
    for meter_id, name in rows:
        names = typed.setdefault(meter_id, [])
        if name not in names:
            names.append(name)
    return typed


def unconnected_text(meter):
    """Why a meter can't go in a formula — the same words as the formula window says."""
    name = f'{meter.name} № {meter.serial}' if meter.serial else meter.name
    return (f'Счётчик «{name}» пока не подключён ни к одной услуге — его показания негде вводить. '
            'Подключите его в услуге «По счётчикам», и тогда его можно будет взять в формулу.')


def formula_problem(property_obj, data, receipt=None):
    """Why the posted formula can't be saved, in one sentence; '' when it is fine. Checked on units only
    (every number counts as 1), so a formula that needs this month's numbers still saves."""
    from . import formula as fx

    numbers = {item['key']: item for item in _clean_numbers((data or {}).get('numbers'))}
    meters = {meter.pk: meter for meter in property_obj.meters.all()}
    blocks = _posted_blocks(data, numbers, set(meters))
    if not blocks:
        return 'Соберите формулу — нажмите «Собрать формулу».'
    owners = formula_owners(property_obj, data, receipt)

    def resolve(block):
        if block['t'] == 'num':
            item = numbers[block['id']]
            if not item['monthly'] and item['value'] is None:
                raise fx.FormulaError(f'У числа «{item["label"]}» не задано значение.')
            return fx.Value(Decimal('1'), fx.units_of(item['unit'], item['per']))
        if not block['meters']:
            raise fx.FormulaError('У счётчика в формуле не отмечен ни один счётчик.')
        return fx.Value(Decimal('1'), fx.units_of(meter_unit(meters[block['meters'][0]]), ''))

    # One meter — one field: a meter no service types the readings of can't be in a formula (2026-11-16).
    typed = typed_meters(property_obj)
    for block in fx.meter_blocks(blocks):
        loose = [meters[pk] for pk in block['meters'] if pk not in typed]
        if loose:
            return unconnected_text(loose[0])
    try:
        fx.evaluate(blocks, resolve)
        if not property_obj.is_owner_used:
            fx.check_mixed(blocks, owners.get)
        if not property_obj.is_owner_used and fx.mode(blocks, owners.get) == 'each':
            fx.payers(blocks, owners.get, list(property_obj.tenants.values_list('pk', flat=True)))
    except fx.FormulaError as error:
        return str(error)
    return ''


@transaction.atomic
def save_formula(receipt, data, today=None):
    """Store the formula window's state: the numbers (new ones made, gone ones removed; a tariff's history kept),
    the blocks, the meters it reads (linked to the service, so their «чей» stays) and their «чей»."""
    from . import formula as fx
    from .models import FormulaNumber

    today = today or date.today()
    property_obj = receipt.property
    existing = {str(number.pk): number for number in receipt.numbers.all()}
    keys = {}
    for position, item in enumerate(_clean_numbers((data or {}).get('numbers'))):
        number = existing.pop(item['key'], None) or FormulaNumber(receipt=receipt)
        number.label, number.monthly, number.unit, number.per = item['label'], item['monthly'], item['unit'], item['per']
        number.value, number.position = item['value'], position
        number.save()
        save_number_value(number, today)
        keys[item['key']] = number.pk
    for number in existing.values():
        receipt.tariffs.filter(key=_number_key(number)).delete()
        number.delete()

    meters = set(property_obj.meters.values_list('pk', flat=True))
    blocks = [dict(block, id=keys[block['id']]) if block['t'] == 'num' else block
              for block in _posted_blocks(data, set(keys), meters)]
    receipt.formula = fx.clean_blocks(blocks, set(keys.values()), meters)

    busy = busy_meters(receipt)
    tenant_ids = set(property_obj.tenants.values_list('pk', flat=True))
    posted = (data or {}).get('owners') or {}
    used_meters = sorted({pk for block in fx.meter_blocks(receipt.formula) for pk in block['meters']})
    for meter in property_obj.meters.filter(pk__in=used_meters):
        if str(meter.pk) in posted and meter.pk not in busy:
            tenant_id, vacant = _posted_owner(posted[str(meter.pk)], tenant_ids)
            if meter.tenant_id != tenant_id or meter.vacant != vacant:
                meter.tenant_id, meter.vacant = tenant_id, vacant
                meter.save(update_fields=['tenant', 'vacant'])
    owners = dict(property_obj.meters.values_list('pk', 'tenant_id'))
    if not property_obj.is_owner_used and fx.mode(receipt.formula, owners.get) == 'each':
        receipt.split = Receipt.Split.METERS  # each pays by his own meters: no «Делим»
    elif receipt.split in (Receipt.Split.METERS, Receipt.Split.USAGE):
        receipt.split = Receipt.Split.SHARES
    receipt.save(update_fields=['formula', 'split'])
    receipt.meters.set(used_meters)
    return receipt


def _parts_text(parts):
    """The formula in numbers for a bill line: «8 450 ₽ ÷ 1 300 кВт·ч × 800 кВт·ч»."""
    words = []
    for part in parts:
        if 'op' in part:
            words.append(part['op'])
        else:
            unit = part.get('unit') or ''
            words.append(fmt_number(part['value']) + (NBSP + unit if unit else ''))
    return ' '.join(words).replace('( ', '(').replace(' )', ')')


def _formula_month(receipt, entry, month, tenants, payers, owner):
    """«Своя формула» in one month. Each pays by his own meters → the tenants' lines here (True: nothing left to
    split); one sum for the object → entry.total, split like any sum after (False). A missing number or reading
    leaves entry.total None (the red dot) and returns True."""
    from . import formula as fx

    entry.readings = _readings_for(receipt.meters.all(), month)
    for meter, _ in entry.readings:
        meter.two_zones = meter.day_night
        meter.mode = meter_mode(receipt, meter)
        meter.tariff_text = ''
    mark_negative(receipt, entry.readings)
    entry.modes = {meter.mode for meter, _ in entry.readings}
    entry.all_usage = entry.modes == {Receipt.InputMode.USAGE}
    entry.some_usage = Receipt.InputMode.USAGE in entry.modes
    numbers = {number.pk: number for number in receipt.numbers.all()}
    # A field only for the «Каждый месяц» numbers that stand in the formula (one kept in the palette only asks nothing).
    used_numbers = {block.get('id') for block in receipt.formula or [] if block.get('t') == 'num'}
    entry.month_numbers = [(number, number_at(number, month)) for number in numbers.values()
                           if number.monthly and number.pk in used_numbers]
    entry.formula_error = ''

    meters = {meter.pk: meter for meter, _ in entry.readings}
    usage = {}
    for meter, reading in entry.readings:
        day, night = used(receipt, reading)
        usage[meter.pk] = None if day is None or (meter.day_night and night is None) else day + (night or Decimal('0'))
    # Meters another service already types («Вода холодная» по счётчикам): the formula just takes their usage — no second
    # field for the same reading on the object page (2026-11-16, the user: «мы не вводим никаких показаний»).
    # One meter — one field: the readings are typed only in the meter's own service; the formula never asks for them.
    typed = typed_meters(receipt.property)
    entry.shared_services = []
    for meter in meters:
        entry.shared_services += [name for name in typed.get(meter, []) if name not in entry.shared_services]
    entry.readings = []
    entry.modes, entry.all_usage, entry.some_usage = set(), False, False
    loose = [meters[pk] for pk in meters if pk not in typed]
    if loose:
        entry.formula_error = unconnected_text(loose[0])
        entry.total = None
        return True
    blocks = receipt.formula or []
    in_formula = {block['id'] for block in blocks if block.get('t') == 'num'}
    if any(value is None for number, value in entry.month_numbers if number.pk in in_formula) or \
            any(usage.get(pk) is None for block in fx.meter_blocks(blocks) for pk in block['meters']):
        entry.total = None
        return True

    def owner_of(pk):
        return meters[pk].tenant_id if pk in meters else None

    def count(tenant_id):
        def resolve(block):
            if block['t'] == 'num':
                number = numbers.get(block['id'])
                if number is None:
                    raise fx.FormulaError('В формуле число, которого больше нет.')
                value = number_at(number, month)
                if value is None:
                    raise fx.FormulaError(f'Не задано «{number.label}».')
                part = {'value': value, 'unit': number_unit_text(number), 'word': number.label}
                return fx.Value(value, fx.units_of(number.unit, number.per), [part])
            if not block['meters']:
                raise fx.FormulaError('У счётчика в формуле не отмечен ни один счётчик.')
            value = fx.meter_usage(block, tenant_id, usage.get, owner_of)
            unit = meter_unit(meters[block['meters'][0]])
            part = {'value': value, 'unit': unit, 'word': '', 'foreign': fx.is_foreign(block, tenant_id, owner_of)}
            return fx.Value(value, fx.units_of(unit, ''), [part])

        result, _ = fx.evaluate(blocks, resolve)
        # «рубли за что-то — это кол-во и тариф» (2026-11-25): the formula's tariff (₽ per unit, a factor of the whole
        # formula) → the bill's «Тариф»; the result ÷ it → «Кол-во» in that unit (to 0,001). None — no such tariff.
        cols = None
        rate = fx.rate_block(blocks, lambda block: fx.units_of(numbers[block['id']].unit, numbers[block['id']].per)
                             if block.get('id') in numbers else {})
        if rate is not None:
            number = numbers[rate['id']]
            tariff = number_at(number, month)
            if tariff:
                cols = ((number.per or '').strip(), (result.value / tariff).quantize(Decimal('0.001')), tariff, Decimal('1'))
        return result.value, _parts_text(fx.drop_foreign(result.parts)), cols

    try:
        if tenants:
            fx.check_mixed(blocks, owner_of)
        each = bool(tenants) and fx.mode(blocks, owner_of) == 'each'
        if not each:
            value, entry.formula_text, _ = count(None)
            entry.total = money(value)
            return False
        payer_ids = fx.payers(blocks, owner_of, [tenant.pk for tenant in tenants])
        excluded = excluded_ids(receipt)
        counted = [(tenant_id, *count(tenant_id)) for tenant_id in payer_ids]
        paying = [(tenant_id, value) for tenant_id, value, _, _ in counted if tenant_id not in excluded]
        off_sum = sum((value for tenant_id, value, _, _ in counted if tenant_id in excluded), Decimal('0'))
        # «Остаётся на вас» off (2026-11-22, as everywhere): the part of those who don't pay goes to those who do,
        # in proportion to their own sums (equally when theirs are all 0).
        pass_on = not receipt.owner_takes and bool(paying) and off_sum > 0
        base = sum((value for _, value in paying), Decimal('0'))
        total = Decimal('0')
        for tenant_id, value, text, cols in counted:
            if tenant_id in excluded:
                if pass_on:
                    continue
                line = Line(receipt, money(value), f'{text} · {payers[tenant_id].tenant.name} не платит')
                owner.lines.append(line)
            else:
                if pass_on:
                    extra = off_sum * value / base if base else off_sum / len(paying)
                    value += extra
                    text = f'{text} + {fmt_number(money(extra))}{NBSP}{receipt.currency_symbol} за неплатящих'
                    cols = None  # a part of others' sums — no «кол-во × тариф» of his own
                line = tenant_line(receipt, value, text, payers[tenant_id].tenant, cols)
                payers[tenant_id].lines.append(line)
            total += line.base
        entry.total = total
    except fx.FormulaError as error:
        entry.formula_error = str(error)
        entry.total = None
    return True


def _last_month(today):
    first = first_of_month(today)
    return date(first.year - 1, 12, 1) if first.month == 1 else date(first.year, first.month - 1, 1)


def owner_numbers(receipt):
    """«Или готовое» (2026-11-24): the formula numbers of the owner's other services — on every object of the account.
    One per name, unit and value (the newest); a monthly number brings only its name and unit, not a month's value."""
    from .models import FormulaNumber

    owner_id = receipt.property.owner_id
    numbers = FormulaNumber.objects.filter(receipt__property__owner_id=owner_id).order_by('-pk')
    if receipt.pk:
        numbers = numbers.exclude(receipt=receipt)
    library, seen = [], set()
    for number in numbers:
        value = None if number.monthly or number.value is None else float(number.value)
        key = (number.label.strip().lower(), number.monthly, number.unit, number.per, value)
        if key in seen:
            continue
        seen.add(key)
        library.append({'label': number.label, 'monthly': number.monthly, 'unit': number.unit,
                        'per': number.per, 'value': value})
    library.sort(key=lambda item: item['label'].lower())
    return library


def formula_context(receipt, data=None, today=None):
    """What the formula window needs (JSON for app.js): the tenants, the object's meters with last month's usage,
    the numbers and the blocks — as posted (a refused save, the way back) or as stored."""
    property_obj = receipt.property
    last = _last_month(today or date.today())
    tenants = [] if property_obj.is_owner_used else list(property_obj.tenants.all())
    typed = typed_meters(property_obj)
    owners = formula_owners(property_obj, data, receipt) if data is not None else None
    meters, kinds = [], {}
    for meter in property_obj.meters.prefetch_related('readings'):
        reading = next((r for r in meter.readings.all() if r.month == last), None)
        usage = None
        if reading is not None:
            day, night = used(receipt, reading)
            if day is not None and (not meter.day_night or night is not None):
                usage = day + (night or Decimal('0'))
        key = meter_kind_key(meter)
        kinds.setdefault(key, {
            'key': key, 'name': meter.name, 'unit': meter_unit(meter),
            'icon': meter.kind if meter.kind in READY_METER_KINDS else 'custom',
        })
        tenant_id = owners[meter.pk] if owners is not None else meter.tenant_id
        meters.append({
            'id': meter.pk, 'key': key, 'serial': meter.serial, 'dn': meter.day_night,
            'tenant': tenant_id, 'vacant': bool(meter.vacant and not tenant_id),
            # Where its readings are typed; none — it can't go in a formula (shown greyed, with why).
            'typed': typed.get(meter.pk, []), 'name': meter.name,
            'last': float(usage) if usage is not None else None,
        })
    if data is not None:
        numbers = [{'id': item['key'], 'label': item['label'], 'monthly': item['monthly'], 'unit': item['unit'],
                    'per': item['per'], 'value': float(item['value']) if item['value'] is not None else None, 'last': None}
                   for item in _clean_numbers(data.get('numbers'))]
        blocks = [block for block in data.get('blocks') or [] if isinstance(block, dict)]
    else:
        numbers = []
        for number in (receipt.numbers.prefetch_related('values') if receipt.pk else []):
            value = number_at(number, last) if number.monthly else number.value
            numbers.append({'id': str(number.pk), 'label': number.label, 'monthly': number.monthly, 'unit': number.unit,
                            'per': number.per, 'value': float(number.value) if number.value is not None else None,
                            'last': float(value) if number.monthly and value is not None else None})
        blocks = [dict(block, id=str(block['id'])) if block.get('t') == 'num' else block for block in receipt.formula or []]
    return {
        'tenants': [{'id': tenant.pk, 'name': tenant.name, 'share': float(tenant.share_percent or 0),
                     'area': float(tenant.area) if tenant.area is not None else None} for tenant in tenants],
        'area': float(property_obj.area) if property_obj.area else None,
        'kinds': list(kinds.values()),
        'meters': meters,
        'numbers': numbers,
        'library': owner_numbers(receipt),
        'blocks': blocks,
        'units': FORMULA_UNITS,
        'symbol': receipt.currency_symbol,
    }


# ---------- «Счётчики → История» (2026-11-25, макет docs/mockups/2026-11-25-meter-history.html) ----------

@dataclass
class HistoryRow:
    """One month of a meter's history. Numbers are Decimals (None — nothing); `price_from_receipt` — «По расходу»:
    the price is the receipt's sum ÷ the usage of all its meters, not a tariff."""

    month: object
    label: str
    missing: bool = False
    was: object = None
    now: object = None
    use: object = None
    was_night: object = None
    now_night: object = None
    use_night: object = None
    price: object = None
    price_night: object = None
    price_from_receipt: bool = False
    price_changed: bool = False
    total: object = None


def _meter_entry(bill, meter):
    """(receipt, entry, reading) of the service that counts by the meter this month; a formula only reads meters."""
    for entry in bill.entries:
        if entry.receipt.amount_mode == Receipt.AmountMode.FORMULA:
            continue
        for one, reading in entry.readings:
            if one.pk == meter.pk:
                return entry.receipt, entry, reading
    return None, None, None


def _receipt_price(receipt, entry, meter):
    """«По расходу»: (price per unit, this meter's part of the receipt) — the same sums as the bill; None — not yet."""
    weight = receipt.night_weight or Decimal('1')
    whole, mine = Decimal('0'), None
    for one, reading in entry.readings:
        day, night = used(receipt, reading)
        if day is None or (two_zones(receipt, one) and night is None):
            return None, None
        use = day + (night * weight if two_zones(receipt, one) else Decimal('0'))
        whole += use
        if one.pk == meter.pk:
            mine = use
    if entry.total is None or not whole or mine is None:
        return None, None
    return entry.total / whole, money(entry.total * mine / whole)


def meter_history(meter, today=None):
    """The meter's months, old to new: from its first month with readings to this month (this one «не введено» while
    empty). «Было» / «стало» as on the object page — for «Расход» meters counted: the start reading plus every usage
    before («было»), + the month's usage («стало»). The price and the sum are the bill's: the meter's tariff of that
    month, or for «По расходу» the receipt's sum ÷ the usage of all its meters. Returns {'rows', 'start', 'start_from',
    'tariffs', 'receipt', 'unit', 'two_zones'}."""
    from apps.properties.services import month_label, shift_month

    this_month = first_of_month(today or date.today())
    months = sorted({reading.month for reading in meter.readings.all()})
    first = months[0] if months else this_month
    rows, month, last_price = [], min(first, this_month), None
    receipt_seen, zones = None, meter.day_night
    while month <= max(this_month, months[-1] if months else this_month):
        bill = month_bill(meter.property, month)
        receipt, entry, reading = _meter_entry(bill, meter)
        if reading is None:
            reading = _readings_for([meter], month)[0][1]
        row = HistoryRow(month=month, label=month_label(month))
        if receipt is not None:
            receipt_seen = receipt
            zones = two_zones(receipt, meter)
            day, night = used(receipt, reading)
        else:
            day, night = reading.consumption, reading.consumption_night
            if reading.current is None and reading.usage is not None:
                day, night = reading.usage, reading.usage_night
        if reading.current is not None:
            row.was, row.now = reading.previous, reading.current
            row.was_night, row.now_night = reading.previous_night, reading.current_night
        else:
            # Not typed as «стало»: what the meter shows before the month is the last «стало» plus every usage typed
            # after it (`counter`, as the object page), so a «Расход» meter's months follow one another.
            counter, counter_night = getattr(reading, 'counter', None), getattr(reading, 'counter_night', None)
            row.was = counter if counter is not None else reading.previous
            row.was_night = counter_night if counter_night is not None else reading.previous_night
            if reading.usage is not None and row.was is not None:
                row.now = row.was + reading.usage
            if zones and reading.usage_night is not None and row.was_night is not None:
                row.now_night = row.was_night + reading.usage_night
        row.use, row.use_night = day, (night if zones else None)
        row.missing = day is None or (zones and night is None)
        if not row.missing and receipt is not None:
            if receipt.metered:
                row.price, row.price_night = meter_price(receipt, entry, meter)
                if row.price is not None:
                    row.total = money(day * row.price + ((night or Decimal('0')) * (row.price_night or Decimal('0'))
                                                         if zones else Decimal('0')))
            elif by_usage(receipt):
                row.price, row.total = _receipt_price(receipt, entry, meter)
                row.price_from_receipt = True
        elif receipt is not None and receipt.metered:
            row.price, row.price_night = meter_price(receipt, entry, meter)
        if row.price is not None and not row.price_from_receipt:
            row.price_changed = last_price is not None and (row.price, row.price_night) != last_price
            last_price = (row.price, row.price_night)
        rows.append(row)
        month = shift_month(month, 1)
    def since(day):  # «с октября 2026»
        return f'с {_MONTHS_GEN[day.month - 1]} {day.year}'

    # «По расходу»: the meter's own tariff isn't used — the price comes from the receipt each month.
    tariffs = [] if receipt_seen is not None and by_usage(receipt_seen) else sorted(
        meter.tariff_history.all(), key=lambda row: row.valid_from)
    return {
        'rows': rows, 'start': meter.initial, 'start_night': meter.initial_night if zones else None,
        'start_from': since(first), 'tariffs': [
            {'from': since(max(row.valid_from, first)), 'tariff': row.tariff,
             'night': row.tariff_night if zones else None, 'now': row is tariffs[-1]} for row in tariffs],
        'receipt': receipt_seen, 'by_usage': receipt_seen is not None and by_usage(receipt_seen),
        'unit': meter_unit(meter), 'two_zones': zones,
    }
