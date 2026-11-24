"""The service window «Услуги · <объект>» (2026-11-19): the object's services on the left, the chosen one on the right,
saved by the «Сохранить» button only. The page draws everything from window_state(); «Сохранить» sends one service
(save_service). «По счётчикам» (2026-11-20): one service — one kind of meters (a group); who pays and «Было / стало |
Расход» — per meter."""

from datetime import date
from decimal import Decimal

from django.db import transaction
from django.urls import reverse

from . import services
from .models import Receipt

# The ways of charging, in the order of the left menu.
MODES = [
    ('receipt', 'По квитанции'),
    ('fixed', 'Фиксированная сумма'),
    ('area', 'По тарифу'),
    ('meters', 'По счётчикам'),
    ('usage', 'По расходу'),  # 2026-11-23: the receipt's sum divided by the meters' usage (no tariff)
    ('formula', 'Своя формула'),
]
SPLITS = [Receipt.Split.SHARES, Receipt.Split.EQUAL, Receipt.Split.AREA]
BASE_UNITS = ['м²', 'чел.', 'м³']


BY_METERS = ('meters', 'usage')  # the modes where a group of meters is chosen and who pays by each


def mode_of(receipt):
    if receipt.metered:
        return 'meters'
    if services.by_usage(receipt):
        return 'usage'
    return {
        Receipt.AmountMode.FORMULA: 'formula',
        Receipt.AmountMode.FIXED: 'fixed',
        Receipt.AmountMode.RATE: 'area',
    }.get(receipt.amount_mode, 'receipt')


def _number(value):
    """Decimal → float for the page (it only shows and recounts; the server counts in Decimal)."""
    return None if value is None else float(value)


def _meter_last_text(meter):
    """«посл. 478 м³» — the meter's last reading (or the start one); '' — none."""
    value, _when = services._last_reading_text(meter)
    if not value:
        return ''
    unit = services.meter_unit(meter)
    return f'посл. {value} {unit}' if not value.startswith('расход') else f'{value} {unit}'


def _meter_tariff_text(meter, today):
    """«9,6 / 4,2 ₽/кВт·ч» — the meter's tariff now; '' — none."""
    row = services.meter_tariff_at(meter, services.first_of_month(today))
    day, night = (row.tariff, row.tariff_night) if row else (meter.tariff, meter.tariff_night)
    if day is None:
        return ''
    price = services.fmt_number(day)
    if meter.day_night:
        price += ' / ' + (services.fmt_number(night) if night is not None else '—')
    unit = services.meter_unit(meter)
    return f'{price}{services.NBSP}₽' + (f'/{unit}' if unit else '')


def _formula_text(receipt):
    """The formula in words: «Расход гор. воды × Норматив × Тариф»; '' — not built yet."""
    if not receipt.formula:
        return ''
    labels = {str(number.pk): number.label for number in receipt.numbers.all()}
    meters = list(receipt.property.meters.all())
    names = {services.meter_kind_key(meter): meter.name for meter in meters}
    by_id = {meter.pk: meter for meter in meters}
    parts = []
    for block in receipt.formula:
        kind = block.get('t')
        if kind == 'num':
            parts.append(labels.get(str(block.get('id')), '?'))
        elif kind == 'meter':
            one = by_id.get((block.get('meters') or [None])[0]) if len(block.get('meters') or []) == 1 else None
            if one is not None:  # a meter of its own (window v2): «Вода холодная № 545575»
                parts.append(f'{one.name} № {one.serial}' if one.serial else one.name)
            else:
                parts.append(names.get(block.get('key'), 'счётчик'))
        elif kind == 'op':
            parts.append(block.get('op', ''))
    return ' '.join(parts).replace('( ', '(').replace(' )', ')')


def window_state(property_obj, selected=None, today=None):
    """Everything the window draws: the tenants, the meters (with who pays by each), the services."""
    today = today or date.today()
    tenants = [] if property_obj.is_owner_used else list(property_obj.tenants.all())
    receipts = list(property_obj.receipts.prefetch_related('meters', 'excluded', 'tariffs'))
    owner_of = {}  # meter id → the service (not a formula: a formula only reads meters)
    for receipt in receipts:
        if receipt.amount_mode != Receipt.AmountMode.FORMULA:
            for meter in receipt.meters.all():
                owner_of.setdefault(meter.pk, receipt)
    meters = []
    readers = services.meter_readers(property_obj)
    for meter in property_obj.meters.prefetch_related('tariff_history', 'excluded', 'readings'):
        service = owner_of.get(meter.pk)
        meters.append({
            'id': meter.pk, 'kind': meter.kind or 'custom', 'name': meter.name, 'serial': meter.serial,
            'group': services.meter_kind_key(meter),
            'input': meter.input_mode or Receipt.InputMode.READINGS,
            'unit': services.meter_unit(meter), 'dn': meter.day_night,
            'tariff': _meter_tariff_text(meter, today),
            'last': _meter_last_text(meter),
            'who': meter.tenant_id or ('owner' if meter.vacant else 'common'),
            'split': meter.split or Receipt.Split.SHARES,
            'excluded': [tenant.pk for tenant in meter.excluded.all()],
            'owner_takes': meter.owner_takes,
            'service': service.pk if service else None,
            'service_name': service.name if service else '',
            'readers': readers.get(meter.pk, []),  # the formulas that read its usage (warned before it leaves)
        })
    groups = []  # the kinds of the object's meters: a service «По счётчикам» takes one of them
    for meter in meters:
        group = next((g for g in groups if g['key'] == meter['group']), None)
        if group is None:
            group = {'key': meter['group'], 'kind': meter['kind'], 'unit': meter['unit'], 'meters': [],
                     'name': next((name for value, name, _ in services.METER_KINDS if value == meter['group']), meter['name'])}
            groups.append(group)
        group['meters'].append(meter['id'])
    own_units = sorted({r.rate_unit for r in Receipt.objects.filter(property__owner=property_obj.owner)
                        if r.rate_unit and r.rate_unit not in BASE_UNITS})
    return {
        'property': {'id': property_obj.pk, 'name': property_obj.name,
                     'area': _number(property_obj.area), 'owner_used': property_obj.is_owner_used},
        'tenants': [{'id': t.pk, 'name': t.name, 'share': _number(t.share_percent or Decimal('0')),
                     'area': _number(t.area)} for t in tenants],
        'meters': meters,
        'groups': groups,
        'services': [service_state(receipt, today) for receipt in receipts],
        # what the formula window of a new «Своя формула» starts from: the object's tenants and meters, no numbers yet
        'fx_new': services.formula_context(Receipt(property=property_obj, kind=Receipt.Kind.CUSTOM), today=today),
        'units': BASE_UNITS, 'own_units': own_units,
        'modes': MODES,
        'selected': selected,
        'urls': {
            'save': reverse('service_save', args=[property_obj.pk]),
            'window': reverse('service_window', args=[property_obj.pk]),
            'object': reverse('property_edit', args=[property_obj.pk]),
        },
    }


def service_state(receipt, today=None):
    mode = mode_of(receipt)
    unit = receipt.rate_unit or ('чел.' if receipt.rate_base == Receipt.RateBase.PERSON else 'м²')
    volume = receipt.volume
    if volume is None and unit == 'чел.' and receipt.persons:
        volume = Decimal(receipt.persons)
    return {
        'id': receipt.pk, 'kind': receipt.kind, 'name': receipt.name, 'provider': receipt.provider, 'mode': mode,
        'split': receipt.split if receipt.split in SPLITS else Receipt.Split.SHARES,
        'excluded': [tenant.pk for tenant in receipt.excluded.all()],
        'owner_takes': receipt.owner_takes,
        'fixed': _number(receipt.fixed_amount),
        'rate': _number(receipt.rate), 'unit': unit, 'volume': _number(volume),
        'meters': [meter.pk for meter in receipt.meters.all()] if mode in BY_METERS else [],
        'group': next((services.meter_kind_key(m) for m in receipt.meters.all()), None) if mode in BY_METERS else None,
        'formula': _formula_text(receipt) if mode == 'formula' else '',
        # «Своя формула»: what its window draws; fx_each — each pays by his own meters (nothing to divide)
        'fx': services.formula_context(receipt, today=today) if mode == 'formula' else None,
        'fx_each': mode == 'formula' and receipt.split == Receipt.Split.METERS,
        'delete_url': reverse('receipt_delete', args=[receipt.pk]),
    }


def _decimal(value):
    if value is None or value == '':
        return None
    return services.parse_decimal(str(value))


def _tenant_ids(property_obj, values):
    own = set(property_obj.tenants.values_list('pk', flat=True))
    return [int(v) for v in values or [] if str(v).isdigit() and int(v) in own]


class WindowError(ValueError):
    pass


@transaction.atomic
def save_service(property_obj, data, today=None):
    """One service as the window has it now (a dict from the page). Returns the saved Receipt."""
    today = today or date.today()
    pk = data.get('id')
    if pk:
        receipt = property_obj.receipts.filter(pk=pk).first()
        if receipt is None:
            raise WindowError('Услуга не найдена.')
    else:
        receipt = Receipt(property=property_obj, kind=data.get('kind') if data.get('kind') in Receipt.Kind.values
                          else Receipt.Kind.CUSTOM)
    name = (data.get('name') or '').strip()[:100]
    if not name:
        raise WindowError('Введите название услуги.')
    provider = (data.get('provider') or '').strip()[:150]
    if not provider:
        raise WindowError('Введите поставщика.')
    mode = data.get('mode')
    if mode not in dict(MODES):
        raise WindowError('Такое начисление здесь не задаётся.')
    receipt.name, receipt.provider = name, provider

    split = data.get('split') if data.get('split') in SPLITS else Receipt.Split.SHARES
    receipt.owner_takes = bool(data.get('owner_takes', True))
    excluded = _tenant_ids(property_obj, data.get('excluded'))
    if mode in BY_METERS:
        return _save_meters(receipt, data, today, usage=mode == 'usage')
    if mode == 'formula':
        return _save_formula(receipt, data, split, excluded, today)

    if receipt.pk:
        receipt.meters.clear()  # not by meters any more: the meters stay the object's, free for another service
    receipt.metered = False
    receipt.split = Receipt.Split.OWNER if property_obj.is_owner_used else split
    receipt.amount_mode = {'receipt': Receipt.AmountMode.MONTHLY, 'fixed': Receipt.AmountMode.FIXED,
                           'area': Receipt.AmountMode.RATE}[mode]
    receipt.fixed_amount = _decimal(data.get('fixed'))
    receipt.rate = _decimal(data.get('rate'))
    receipt.rate_unit = (data.get('unit') or 'м²').strip()[:12] if mode == 'area' else ''
    receipt.rate_base = Receipt.RateBase.AREA
    receipt.persons = None
    receipt.volume = _decimal(data.get('volume'))
    if mode == 'area' and receipt.rate_unit == 'м²' and receipt.volume == property_obj.area:
        receipt.volume = None  # м² of the whole object: follows the object's area
    services.save_receipt(receipt, excluded=excluded, today=today)
    return receipt


def _save_formula(receipt, data, split, excluded, today):
    """«Своя формула» (2026-11-20): the formula window's state (data['formula']: numbers, blocks, who uses each meter),
    checked as the old window did; None — the stored formula stays as it is. «Делим» — as for a receipt; each by his own
    meters — save_formula sets it."""
    property_obj = receipt.property
    formula = data.get('formula')
    kept = formula is None and receipt.pk and mode_of(receipt) == 'formula'  # only the name, supplier or «Делим» changed
    if not kept:
        problem = services.formula_problem(property_obj, formula if isinstance(formula, dict) else {},
                                           receipt if receipt.pk else None)
        if problem:
            raise WindowError(problem)
    each = kept and receipt.split == Receipt.Split.METERS
    receipt.metered = False
    receipt.amount_mode = Receipt.AmountMode.FORMULA
    receipt.split = Receipt.Split.OWNER if property_obj.is_owner_used else Receipt.Split.METERS if each else split
    receipt.fixed_amount = receipt.rate = receipt.volume = None
    receipt.rate_unit = ''
    # the meters it reads are linked by save_formula; a kept formula keeps its meters
    services.save_receipt(receipt, excluded=excluded, today=today, formula=None if kept else formula)
    return receipt


def _save_meters(receipt, data, today, usage=False):
    """«По счётчикам» (2026-11-20): every meter of one kind (data['group']) and, per meter, who pays — a tenant,
    the owner, or common (divided) — and what is typed each month («Было / стало» or «Расход»).
    usage — «По расходу» (2026-11-23): the same meters, but the month's sum is the receipt's, divided in proportion to
    their usage; no tariff, and a meter is a tenant's or the owner's (a common one's part is the owner's)."""
    property_obj = receipt.property
    tenants = set(property_obj.tenants.values_list('pk', flat=True))
    busy = services.busy_meters(receipt)
    group = data.get('group')
    rows = {int(row['id']): row for row in data.get('meters') or [] if str(row.get('id', '')).isdigit()}
    in_group = [m for m in property_obj.meters.all() if services.meter_kind_key(m) == group]
    if not group or not in_group:
        raise WindowError('Выберите счётчики.')
    # Meters are chosen one by one (2026-11-24, tiles): only the meters sent are the service's; a meter outside every
    # service just stays on the object and is not counted anywhere.
    meters = [m for m in in_group if m.pk in rows]
    if not meters:
        raise WindowError('Выберите счётчики.')
    if any(meter.pk in busy for meter in meters):
        raise WindowError('Эти счётчики уже в другой услуге.')
    for meter in meters:
        row = rows.get(meter.pk) or {}
        who = row.get('who')
        if property_obj.is_owner_used or who == 'owner':
            meter.tenant, meter.vacant, meter.split = None, not property_obj.is_owner_used, ''
        elif who == 'common' and not usage:
            meter.tenant, meter.vacant = None, False
            meter.split = row.get('split') if row.get('split') in SPLITS else Receipt.Split.SHARES
            meter.owner_takes = bool(row.get('owner_takes', True))
        elif str(who).isdigit() and int(who) in tenants:
            meter.tenant_id, meter.vacant, meter.split = int(who), False, ''
        else:
            raise WindowError(f'Выберите, кто платит по счётчику № {meter.serial or meter.pk}.')
        if row.get('input') in Receipt.InputMode.values:
            meter.input_mode = row['input']
        meter.save()
        if meter.split:
            meter.excluded.set(_tenant_ids(property_obj, row.get('excluded')))
    receipt.kind = meters[0].kind if meters[0].kind in Receipt.Kind.values else Receipt.Kind.CUSTOM
    receipt.amount_mode = Receipt.AmountMode.MONTHLY
    if usage:
        receipt.metered = False
        receipt.layout = Receipt.Layout.COMMON
        receipt.split = Receipt.Split.OWNER if property_obj.is_owner_used else Receipt.Split.USAGE
    else:
        receipt.metered = True
        receipt.layout = Receipt.Layout.COMMON if property_obj.is_owner_used else Receipt.Layout.TENANTS
        receipt.split = Receipt.Split.OWNER if property_obj.is_owner_used else Receipt.Split.METERS
        receipt.zones = 2 if any(meter.day_night for meter in meters) else 1
        receipt.unit = services.meter_unit(meters[0]) or receipt.unit or 'ед.'
    receipt.fixed_amount = receipt.rate = receipt.volume = None
    receipt.rate_unit = ''
    services.normalize(receipt)
    receipt.save()
    receipt.meters.set(meters)
    receipt.excluded.clear()
    services.release_free_meters(property_obj)
    return receipt
