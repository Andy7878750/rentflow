"""Business logic for receipts (квитанции) and meters.

Two parts: the one-time setup of an object's receipts, and the monthly input
(amounts, tariffs, readings) with the split between tenants.
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction

from .models import Meter, MonthlyAmount, Reading, Receipt

# Sensible defaults for each ready-made receipt, so the lazy landlord mostly just confirms.
PRESETS = {
    Receipt.Kind.MANAGEMENT: {'split': Receipt.Split.SHARES},
    Receipt.Kind.ELECTRICITY: {'metered': True, 'unit': 'кВт·ч', 'split': Receipt.Split.METERS},
    Receipt.Kind.WATER: {'metered': True, 'unit': 'м³', 'split': Receipt.Split.METERS},
    Receipt.Kind.HOT_WATER: {'metered': True, 'unit': 'м³', 'split': Receipt.Split.METERS},
    # Heating of hot water (Гкал) and sewage (= cold + hot) are simplified for now: by meters, in м³.
    Receipt.Kind.HOT_WATER_HEATING: {'metered': True, 'unit': 'м³', 'split': Receipt.Split.METERS},
    Receipt.Kind.SEWAGE: {'metered': True, 'unit': 'м³', 'split': Receipt.Split.METERS},
    Receipt.Kind.HEATING: {'split': Receipt.Split.AREA},
    Receipt.Kind.GAS: {'metered': True, 'unit': 'м³', 'split': Receipt.Split.METERS},
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
        receipt.split = Receipt.Split.METERS if receipt.metered else Receipt.Split.OWNER
    return receipt


def template_tiles(property_obj, selected):
    """Template tiles of «Новая услуга»: every ready-made kind, the picked one and the ones already added marked."""
    have = set(property_obj.receipts.values_list('kind', flat=True))
    return [
        {'kind': kind, 'label': kind.label, 'selected': kind == selected, 'added': kind in have}
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
    if not receipt.metered:
        receipt.unit = ''
        receipt.tariff = None
        if receipt.split == Receipt.Split.METERS:
            receipt.split = Receipt.Split.SHARES
    else:
        # The amount follows the readings, so it can't be a fixed sum.
        receipt.amount_mode = Receipt.AmountMode.MONTHLY
        if not receipt.unit:
            receipt.unit = 'ед.'
    if receipt.amount_mode != Receipt.AmountMode.FIXED:
        receipt.fixed_amount = None
    if receipt.property.is_owner_used and receipt.split != Receipt.Split.METERS:
        receipt.split = Receipt.Split.OWNER
    return receipt


def sync_meters(receipt):
    """Keep the receipt's meters in line with its settings.

    Split by readings → one meter per tenant (each has their own). Metered but split
    another way, or the owner uses the object → one common meter. Not metered → none.
    Existing meters are kept where possible, so their history survives an edit.
    """
    tenants = [] if receipt.property.is_owner_used else list(receipt.property.tenants.all())
    if not receipt.metered:
        wanted = {}
    elif receipt.split == Receipt.Split.METERS and tenants:
        wanted = {tenant.pk: tenant.name for tenant in tenants}
    else:
        wanted = {None: 'Общий счётчик'}

    existing = {meter.tenant_id: meter for meter in receipt.meters.all()}
    for tenant_id, meter in existing.items():
        if tenant_id not in wanted:
            meter.delete()
    for tenant_id, name in wanted.items():
        meter = existing.get(tenant_id)
        if meter is None:
            Meter.objects.create(receipt=receipt, tenant_id=tenant_id, name=name)
        elif meter.name != name:
            meter.name = name
            meter.save(update_fields=['name'])


@transaction.atomic
def save_receipt(receipt):
    normalize(receipt)
    receipt.save()
    sync_meters(receipt)
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
        save_receipt(receipt)


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
    tariff: object = None                        # effective tariff for metered receipts
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
    """This month's reading for each meter; «было» defaults to last month's «стало»."""
    result = []
    for meter in meters:
        readings = list(meter.readings.all())
        reading = next((r for r in readings if r.month == month), None) or Reading(meter=meter, month=month)
        if reading.previous is None:
            earlier = [r for r in readings if r.month < month and r.current is not None]
            if earlier:
                reading.previous = earlier[-1].current
        result.append((meter, reading))
    return result


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

    for receipt in property_obj.receipts.prefetch_related('meters__readings', 'monthly_amounts'):
        amount = next((a for a in receipt.monthly_amounts.all() if a.month == month), None)
        entry = MonthEntry(receipt=receipt, amount=amount)
        entries.append(entry)

        if receipt.metered:
            entry.tariff = amount.tariff if amount and amount.tariff is not None else receipt.tariff
            entry.readings = _readings_for(receipt.meters.all(), month)
            readings_total += len(entry.readings)
            readings_done += sum(1 for _, r in entry.readings if r.consumption is not None)
            if entry.tariff is None or any(r.consumption is None for _, r in entry.readings):
                continue
            if receipt.split == Receipt.Split.METERS:
                # Each tenant pays for what their own meter shows.
                entry.total = Decimal('0')
                for meter, reading in entry.readings:
                    formula = (f'{fmt_number(reading.consumption)} {receipt.unit} × '
                               f'{fmt_number(entry.tariff)}{NBSP}{receipt.currency_symbol}')
                    payer = payers.get(meter.tenant_id)
                    if payer:
                        line = tenant_line(receipt, reading.consumption * entry.tariff, formula)
                    else:
                        line = Line(receipt, money(reading.consumption * entry.tariff), formula)
                    (payer or owner).lines.append(line)
                    entry.total += line.base
                continue
            consumption = sum((r.consumption for _, r in entry.readings), Decimal('0'))
            entry.total = money(consumption * entry.tariff)
        elif receipt.amount_mode == Receipt.AmountMode.FIXED:
            entry.total = receipt.fixed_amount
        else:
            entry.total = amount.amount if amount else None

        if entry.total is None:
            continue
        lines = {} if receipt.split == Receipt.Split.OWNER else _split(entry.total, receipt, tenants, property_obj)
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

    Field names: amount-<receipt>, tariff-<receipt>, prev-<meter>, cur-<meter>, and
    coef-<receipt> — the coefficient belongs to the receipt itself, not to the month.
    Only posted fields change; an emptied field clears the stored value.
    """
    for receipt in property_obj.receipts.prefetch_related('meters'):
        if f'coef-{receipt.pk}' in data:
            coefficient = parse_decimal(data.get(f'coef-{receipt.pk}'))
            if coefficient is None or coefficient <= 0 or coefficient >= 100:
                coefficient = Decimal('1')
            if coefficient != receipt.coefficient:
                receipt.coefficient = coefficient
                receipt.save(update_fields=['coefficient'])
        keys = (f'amount-{receipt.pk}', f'tariff-{receipt.pk}')
        if any(key in data for key in keys):
            row, _ = MonthlyAmount.objects.get_or_create(receipt=receipt, month=month)
            if keys[0] in data:
                row.amount = parse_decimal(data.get(keys[0]))
            if keys[1] in data:
                row.tariff = parse_decimal(data.get(keys[1]))
            row.save()
        for meter in receipt.meters.all():
            keys = (f'prev-{meter.pk}', f'cur-{meter.pk}')
            if any(key in data for key in keys):
                reading, _ = Reading.objects.get_or_create(meter=meter, month=month)
                if keys[0] in data:
                    reading.previous = parse_decimal(data.get(keys[0]))
                if keys[1] in data:
                    reading.current = parse_decimal(data.get(keys[1]))
                reading.save()
