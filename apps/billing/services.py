"""Business logic for receipts (квитанции) and meters.

Two parts: the one-time setup of an object's receipts, and the monthly input
(amounts, tariffs, readings) with the split between tenants.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction

from .models import Meter, MonthlyAmount, Reading, Receipt

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

# Kinds offered as one-click buttons («Какие квитанции приходят?»), in this order.
OFFERED_KINDS = [kind for kind in Receipt.Kind if kind != Receipt.Kind.CUSTOM]


def new_receipt(property_obj, kind):
    """An unsaved receipt of the given kind with its defaults filled in."""
    if kind not in Receipt.Kind.values:
        kind = Receipt.Kind.CUSTOM
    receipt = Receipt(property=property_obj, kind=kind)
    receipt.name = '' if kind == Receipt.Kind.CUSTOM else Receipt.Kind(kind).label
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
        {'kind': kind, 'label': tile_label(kind.label), 'name': kind.label, 'selected': kind == selected, 'added': kind in have}
        for kind in OFFERED_KINDS
    ]


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
        receipt.input_mode = Receipt.InputMode.READINGS
        if receipt.split == Receipt.Split.METERS:
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
        elif receipt.split == Receipt.Split.METERS:
            receipt.split = Receipt.Split.SHARES
    if receipt.amount_mode != Receipt.AmountMode.FIXED:
        receipt.fixed_amount = None
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


def meter_counts(property_obj):
    """How many meters each layout gives, for the badge in the head of «Счётчики»."""
    tenants = 0 if property_obj.is_owner_used else property_obj.tenants.count()
    if not tenants:
        return [{'value': 'any', 'count': meters_label(1)}]
    return [
        {'value': Receipt.Layout.COMMON, 'count': meters_label(1)},
        {'value': Receipt.Layout.TENANTS, 'count': meters_label(tenants)},
        {'value': Receipt.Layout.BOTH, 'count': meters_label(tenants + 1)},
    ]


def _meter_key(tenant_id):
    return 'common' if tenant_id is None else f't{tenant_id}'


# What a meter measures: the ready-made kinds of the «Что за счётчик» menu, with their units.
METER_KINDS = [
    (Receipt.Kind.ELECTRICITY, 'Электричество', 'кВт·ч'),
    (Receipt.Kind.WATER, 'Вода холодная', 'м³'),
    (Receipt.Kind.HOT_WATER, 'Вода горячая', 'м³'),
    (Receipt.Kind.GAS, 'Газ', 'м³'),
    (Receipt.Kind.HEATING, 'Отопление', 'Гкал'),
]
# The «Что за счётчик» menu offers only these; gas and heating meters keep their names when a template sets them.
MENU_METER_KINDS = {Receipt.Kind.ELECTRICITY, Receipt.Kind.WATER, Receipt.Kind.HOT_WATER}
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


def meters_without_tariff(meters, zones):
    """Indexes of the meters whose tariff is not typed (with day / night — either of the two)."""
    return [
        index for index, values in enumerate(meters)
        if values['tariff'] is None or (zones == 2 and values['tariff_night'] is None)
    ]


def tariff_from_meters(receipt, meters, tenant_id=None):
    """The service's tariff and unit = those of its meter (the tenant's, if asked, else the first with a tariff).
    The tariff is typed per meter in the window; the service keeps one for the month history and «Формула»."""
    with_tariff = [values for values in meters if values['tariff'] is not None]
    if not with_tariff:
        return receipt
    chosen = next((values for values in with_tariff if tenant_id and str(values['tenant_id']) == str(tenant_id)), with_tariff[0])
    receipt.tariff = chosen['tariff']
    receipt.tariff_night = chosen['tariff_night']
    receipt.unit = chosen['unit'] or receipt.unit
    return receipt


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


@transaction.atomic
def delete_receipt(receipt):
    meters = list(receipt.meters.all())
    receipt.delete()
    for meter in meters:
        drop_if_unused(meter)


@transaction.atomic
def save_receipt(receipt, meters=None, today=None, excluded=None, keep_meters=False):
    """Save the service. meters — the list from the service window (parse_meters); without it
    (saved from code) the meters follow the service's layout.
    keep_meters — the object's tenants changed: the service keeps the meters it has (they are the
    premises'; who pays by each is set on the object), only its layout follows them.
    excluded — tenants switched off in «Кто платит» (parse_excluded); None keeps them as they are."""
    old = Receipt.objects.filter(pk=receipt.pk).values('tariff', 'tariff_night').first() if receipt.pk else None
    linked = list(receipt.meters.all()) if keep_meters and receipt.pk and receipt.metered else []
    if linked and not meters and not receipt.property.is_owner_used:
        # A free meter (its tenant moved out) still counts as a tenant's one, not a common one.
        meters = None
        receipt.layout = layout_for([{'tenant_id': m.tenant_id or ('free' if m.vacant else None)} for m in linked])
    if meters and receipt.metered and not receipt.property.is_owner_used:
        receipt.layout = layout_for(meters)
    normalize(receipt)
    receipt.save()
    if old and receipt.metered:
        keep_past_tariffs(receipt, old['tariff'], old['tariff_night'], today or date.today())
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


# ---------------------------------------------------------------------------
# Monthly input and the split between tenants
# ---------------------------------------------------------------------------

CENT = Decimal('0.01')
HUNDRED = Decimal('100')
NBSP = ' '


def money(value):
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


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

    def __post_init__(self):
        if self.base is None:
            self.base = self.amount


def tenant_line(receipt, exact, formula):
    """A tenant's line: their exact part of the receipt, times the receipt's coefficient."""
    coefficient = receipt.coefficient
    if coefficient == 1:
        return Line(receipt, money(exact), formula)
    return Line(receipt, money(exact * coefficient), f'{formula} × {fmt_number(coefficient)}', base=money(exact))


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
        result.append((meter, reading))
    return result


def used(receipt, reading):
    """(day, night) usage of one meter's month: typed as is («Расход») or «стало − было» («Показания»)."""
    if receipt.input_mode == Receipt.InputMode.USAGE:
        return reading.usage, reading.usage_night
    return reading.consumption, reading.consumption_night


def _meter_cost(receipt, entry, reading):
    """(exact cost, formula) of one meter's month, or None while something is missing."""
    meter = reading.meter
    unit, currency = meter.unit or receipt.unit, receipt.currency_symbol
    # A meter with its own tariff counts by it; otherwise by the service's.
    tariff = meter.tariff if meter.tariff is not None else entry.tariff
    tariff_night = meter.tariff_night if meter.tariff_night is not None else entry.tariff_night
    day, night = used(receipt, reading)
    if tariff is None or day is None:
        return None
    if receipt.zones != 2:
        formula = f'{fmt_number(day)} {unit} × {fmt_number(tariff)}{NBSP}{currency}'
        return day * tariff, formula
    if tariff_night is None or night is None:
        return None
    formula = (f'день {fmt_number(day)} {unit} × {fmt_number(tariff)}{NBSP}{currency} + '
               f'ночь {fmt_number(night)} {unit} × {fmt_number(tariff_night)}{NBSP}{currency}')
    return day * tariff + night * tariff_night, formula


def _split(total, receipt, tenants, property_obj):
    """Split a receipt's total between tenants. Returns {tenant_id: Line}."""
    currency = receipt.currency_symbol
    total_text = f'{fmt_number(total, 2)}{NBSP}{currency}'
    lines = {}
    if receipt.split == Receipt.Split.SHARES:
        for tenant in tenants:
            share = tenant.share_percent or Decimal('0')
            lines[tenant.pk] = tenant_line(receipt, total * share / HUNDRED, f'{total_text} × {fmt_number(share)}%')
    elif receipt.split == Receipt.Split.EQUAL and tenants:
        for tenant in tenants:
            lines[tenant.pk] = tenant_line(receipt, total / len(tenants), f'{total_text} ÷ {len(tenants)}')
    elif receipt.split == Receipt.Split.AREA and property_obj.area:
        for tenant in tenants:
            area = tenant.area or Decimal('0')
            lines[tenant.pk] = tenant_line(
                receipt, total * area / property_obj.area,
                f'{total_text} × {fmt_number(area)} из {fmt_number(property_obj.area)}{NBSP}м²',
            )
    return lines


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
    fixed = (
        not receipt.metered and receipt.amount_mode == Receipt.AmountMode.FIXED
        and receipt.fixed_amount and receipt.split != Receipt.Split.OWNER
    )
    lines = _split(receipt.fixed_amount, receipt, paying, property_obj) if fixed else {}
    rows = []
    for tenant in tenants:
        pays = tenant.pk not in excluded
        if not pays:
            basis = ''
        elif receipt.split == Receipt.Split.EQUAL:
            basis = f'÷ {len(paying)}'
        elif receipt.split == Receipt.Split.AREA:
            basis = f'{fmt_number(tenant.area)}{NBSP}м²' if tenant.area is not None else '— м²'
        elif receipt.split == Receipt.Split.SHARES:
            basis = f'{fmt_number(tenant.share_percent or Decimal("0"))}%'
        else:
            basis = ''
        line = lines.get(tenant.pk)
        rows.append(PayerPreview(tenant, basis, _rub(line.amount, receipt.currency_symbol) if line else '', pays))
    return rows


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

    for receipt in property_obj.receipts.prefetch_related('meters__readings', 'meters__tenant', 'monthly_amounts', 'excluded'):
        amount = next((a for a in receipt.monthly_amounts.all() if a.month == month), None)
        entry = MonthEntry(receipt=receipt, amount=amount)
        entries.append(entry)

        if receipt.metered:
            # A past month keeps the tariff it was billed at; otherwise the service's current one.
            if amount and (amount.tariff is not None or amount.tariff_night is not None):
                entry.tariff, entry.tariff_night = amount.tariff, amount.tariff_night
            else:
                entry.tariff, entry.tariff_night = receipt.tariff, receipt.tariff_night
            entry.readings = _readings_for(receipt.meters.all(), month)
            costs = [(meter, _meter_cost(receipt, entry, reading)) for meter, reading in entry.readings]
            readings_total += len(costs)
            readings_done += sum(1 for _, cost in costs if cost is not None)
            if any(cost is None for _, cost in costs):
                continue
            if receipt.split == Receipt.Split.METERS:
                # Each tenant pays for what their own meter shows.
                common = None
                billed = Decimal('0')
                for meter, (exact, formula) in costs:
                    payer = payers.get(meter.tenant_id)
                    if meter.vacant and not meter.tenant_id:
                        # A free meter: its tenant moved out, the owner pays until a new one takes it.
                        line = Line(receipt, money(exact), f'{formula} · свободный счётчик')
                        owner.lines.append(line)
                        billed += line.base
                    elif meter.tenant_id is None and receipt.layout == Receipt.Layout.BOTH:
                        common = (common or Decimal('0')) + exact
                    elif payer:
                        line = tenant_line(receipt, exact, formula)
                        payer.lines.append(line)
                        billed += line.base
                    else:
                        line = Line(receipt, money(exact), formula)
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
        elif receipt.amount_mode == Receipt.AmountMode.FIXED:
            entry.total = receipt.fixed_amount
        else:
            entry.total = amount.amount if amount else None

        if entry.total is None:
            continue
        # Tenants switched off in «Кто платит» don't pay: their part stays with the owner.
        excluded = excluded_ids(receipt)
        paying = [tenant for tenant in tenants if tenant.pk not in excluded]
        lines = {} if receipt.split == Receipt.Split.OWNER else _split(entry.total, receipt, paying, property_obj)
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
        if tenant and receipt.coefficient != 1:
            items += [op('×'), term('Коэффициент', fmt_number(receipt.coefficient))]

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
            amount = tenant_line(receipt, exact, '').amount
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
    amount = tenant_line(receipt, exact, '').amount
    steps.append(FormulaStep(items, _rub(amount, currency)))
    return FormulaExample(choices, str(tenant.pk), tenant.name, amount, _rub(amount, currency), steps)
