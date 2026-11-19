"""The service window «Услуги · <объект>» (2026-11-19): the object's services on the left, the chosen one on the right,
saved by itself on every change. The page draws everything from window_state(); every change comes back as one
service (save_service)."""

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
    ('formula', 'Своя формула'),
]
SPLITS = [Receipt.Split.SHARES, Receipt.Split.EQUAL, Receipt.Split.AREA]
BASE_UNITS = ['м²', 'чел.', 'м³']


def mode_of(receipt):
    if receipt.metered:
        return 'meters'
    return {
        Receipt.AmountMode.FORMULA: 'formula',
        Receipt.AmountMode.FIXED: 'fixed',
        Receipt.AmountMode.RATE: 'area',
    }.get(receipt.amount_mode, 'receipt')


def _number(value):
    """Decimal → float for the page (it only shows and recounts; the server counts in Decimal)."""
    return None if value is None else float(value)


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
    """The formula in words: «Расход гор. воды × Норматив × Тариф»."""
    if not receipt.formula:
        return 'Формула ещё не собрана'
    labels = {str(number.pk): number.label for number in receipt.numbers.all()}
    names = {services.meter_kind_key(meter): meter.name for meter in receipt.property.meters.all()}
    parts = []
    for block in receipt.formula:
        kind = block.get('t')
        if kind == 'num':
            parts.append(labels.get(str(block.get('id')), '?'))
        elif kind == 'meter':
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
    for meter in property_obj.meters.prefetch_related('tariff_history', 'excluded'):
        service = owner_of.get(meter.pk)
        meters.append({
            'id': meter.pk, 'kind': meter.kind or 'custom', 'name': meter.name, 'serial': meter.serial,
            'unit': services.meter_unit(meter), 'dn': meter.day_night,
            'tariff': _meter_tariff_text(meter, today),
            'who': meter.tenant_id or ('owner' if meter.vacant else 'common'),
            'split': meter.split or Receipt.Split.SHARES,
            'excluded': [tenant.pk for tenant in meter.excluded.all()],
            'owner_takes': meter.owner_takes,
            'service': service.pk if service else None,
            'service_name': service.name if service else '',
        })
    own_units = sorted({r.rate_unit for r in Receipt.objects.filter(property__owner=property_obj.owner)
                        if r.rate_unit and r.rate_unit not in BASE_UNITS})
    return {
        'property': {'id': property_obj.pk, 'name': property_obj.name,
                     'area': _number(property_obj.area), 'owner_used': property_obj.is_owner_used},
        'tenants': [{'id': t.pk, 'name': t.name, 'share': _number(t.share_percent or Decimal('0')),
                     'area': _number(t.area)} for t in tenants],
        'meters': meters,
        'services': [service_state(receipt) for receipt in receipts],
        'units': BASE_UNITS, 'own_units': own_units,
        'modes': MODES,
        'selected': selected,
        'urls': {
            'save': reverse('service_save', args=[property_obj.pk]),
            'object': reverse('property_edit', args=[property_obj.pk]),
            'formula_new': reverse('receipt_create', args=[property_obj.pk]) + '?kind=custom',
        },
    }


def service_state(receipt):
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
        'meters': [meter.pk for meter in receipt.meters.all()] if mode == 'meters' else [],
        'formula': _formula_text(receipt) if mode == 'formula' else '',
        'edit_url': reverse('receipt_edit', args=[receipt.pk]),
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
    mode = data.get('mode')
    if mode not in dict(MODES) or mode == 'formula' and mode_of(receipt) != 'formula':
        raise WindowError('Такое начисление здесь пока не задаётся.')
    receipt.name, receipt.provider = name, (data.get('provider') or '').strip()[:150]
    if mode == 'formula':
        receipt.save(update_fields=['name', 'provider'] if receipt.pk else None)
        return receipt

    split = data.get('split') if data.get('split') in SPLITS else Receipt.Split.SHARES
    receipt.owner_takes = bool(data.get('owner_takes', True))
    excluded = _tenant_ids(property_obj, data.get('excluded'))
    if mode == 'meters':
        return _save_meters(receipt, data, today)

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


def _save_meters(receipt, data, today):
    """«По счётчикам»: the switched-on meters and who pays by each — a tenant, the owner, or common (divided)."""
    property_obj = receipt.property
    tenants = set(property_obj.tenants.values_list('pk', flat=True))
    busy = services.busy_meters(receipt)
    rows = {int(row['id']): row for row in data.get('meters') or [] if str(row.get('id', '')).isdigit()}
    on = []
    for meter in property_obj.meters.filter(pk__in=list(rows)):
        row = rows[meter.pk]
        if meter.pk in busy or not row.get('on'):
            continue
        on.append(meter)
        who = row.get('who')
        if property_obj.is_owner_used or who == 'owner':
            meter.tenant, meter.vacant, meter.split = None, not property_obj.is_owner_used, ''
        elif who == 'common':
            meter.tenant, meter.vacant = None, False
            meter.split = row.get('split') if row.get('split') in SPLITS else Receipt.Split.SHARES
            meter.owner_takes = bool(row.get('owner_takes', True))
        elif str(who).isdigit() and int(who) in tenants:
            meter.tenant_id, meter.vacant, meter.split = int(who), False, ''
        meter.save()
        if meter.split:
            meter.excluded.set(_tenant_ids(property_obj, row.get('excluded')))
    receipt.metered = True
    receipt.amount_mode = Receipt.AmountMode.MONTHLY
    receipt.layout = Receipt.Layout.COMMON if property_obj.is_owner_used else Receipt.Layout.TENANTS
    receipt.split = Receipt.Split.OWNER if property_obj.is_owner_used else Receipt.Split.METERS
    receipt.zones = 2 if any(meter.day_night for meter in on) else 1
    receipt.unit = services.meter_unit(on[0]) if on else (receipt.unit or 'ед.')
    receipt.fixed_amount = receipt.rate = receipt.volume = None
    receipt.rate_unit = ''
    services.normalize(receipt)
    receipt.save()
    receipt.meters.set(on)
    receipt.excluded.clear()
    services.release_free_meters(property_obj)
    return receipt
