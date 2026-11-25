"""«Своя формула»: the owner's own formula of numbers, meters and signs (2026-11-16).

The formula is a list of blocks (Receipt.formula):
    {"t": "num", "id": <FormulaNumber id>}                              — a number: «Каждый месяц» or «Тариф / норматив»
    {"t": "meter", "key": "electricity", "meters": [ids], "join": "each" | "sum"}  — the month's usage of meters
    {"t": "op", "op": "+" | "−" | "×" | "÷" | "(" | ")"}

It is counted here without eval: a small parser (sum → product → primary) over Decimal, each value carrying
its units as powers (45 ₽/м³ → {'₽': 1, 'м³': -1}). The result must come out in rubles; a number without a unit
switches that check off for the formula.

Who pays follows from the formula itself (no «Как считаем»). Since 2026-11-21 (window v2) each meter is a block of
its own: meters of tenants → each tenant pays by his own meters (another tenant's meter is 0 for him, and drops out of
his bill line); only common meters → one sum for the object, split as the service says («Делим»). Common meters and
tenants' meters in one formula are refused. Older blocks of several meters («у каждого свой» / «складываем») still count.
"""

from dataclasses import dataclass, field
from decimal import Decimal, DivisionByZero, InvalidOperation

SIGNS = ('+', '−', '×', '÷', '(', ')')
RUB = {'₽': 1}


class FormulaError(Exception):
    """A formula that can't be counted — the message is said to the owner as is."""


@dataclass
class Value:
    value: Decimal
    units: dict
    parts: list = field(default_factory=list)  # [{'value', 'unit', 'word', 'sample'}] and [{'op'}] — for «Как посчитается»


def units_of(unit, per):
    # «-», «—» typed for «no unit» (a coefficient) is no unit, not a unit of its own.
    unit, per = ((text or '').strip().strip('-–—_.').strip() and text.strip() for text in (unit, per))
    units = {}
    if unit:
        units[unit] = 1
    if per:
        units[per] = units.get(per, 0) - 1
        if not units[per]:
            del units[per]
    return units


def _combine(a, b, sign):
    units = dict(a)
    for key, power in b.items():
        units[key] = units.get(key, 0) + sign * power
        if not units[key]:
            del units[key]
    return units


def unit_text(units):
    """{'₽': 1, 'м³': -1} → «₽/м³»; {} → «число»."""
    up = [key for key, power in units.items() if power > 0]
    down = [key for key, power in units.items() if power < 0]
    if not up and not down:
        return 'число'
    return ('·'.join(up) or '1') + ('/' + '·'.join(down) if down else '')


def evaluate(blocks, resolve):
    """Count the blocks. resolve(block) → Value of a number or meter block (raises FormulaError when it can't).
    Returns (Value, bare): bare — a number without a unit stood in it (the ₽ check is off).
    Raises FormulaError with a plain sentence."""
    if not blocks:
        raise FormulaError('Формула ещё не собрана.')
    state = {'i': 0, 'bare': False}

    def at():
        return blocks[state['i']] if state['i'] < len(blocks) else None

    def is_op(block, *ops):
        return block is not None and block.get('t') == 'op' and block.get('op') in ops

    def primary():
        block = at()
        if block is None:
            raise FormulaError('Формула обрывается — добавьте число или счётчик в конце.')
        if is_op(block, '('):
            state['i'] += 1
            inner = total()
            if not is_op(at(), ')'):
                raise FormulaError('Не хватает закрывающей скобки «)».')
            state['i'] += 1
            return Value(inner.value, inner.units, [{'op': '('}, *inner.parts, {'op': ')'}])
        if block.get('t') == 'op':
            raise FormulaError(f'Знак «{block.get("op")}» стоит не на месте.')
        state['i'] += 1
        value = resolve(block)
        if block.get('t') == 'num' and not value.units:
            state['bare'] = True
        return value

    def product():
        a = primary()
        while is_op(at(), '×', '÷'):
            op = at()['op']
            state['i'] += 1
            b = primary()
            if op == '÷' and not b.value:
                raise FormulaError('Делим на ноль: ' + (b.parts[0].get('word', '') if b.parts else 'ноль') + ' = 0.')
            try:
                result = a.value * b.value if op == '×' else a.value / b.value
            except (InvalidOperation, DivisionByZero):
                raise FormulaError('Делим на ноль.') from None
            a = Value(result, _combine(a.units, b.units, 1 if op == '×' else -1), [*a.parts, {'op': op}, *b.parts])
        return a

    def total():
        a = product()
        while is_op(at(), '+', '−'):
            op = at()['op']
            state['i'] += 1
            b = product()
            if not state['bare'] and a.units != b.units:
                verb = 'складывать' if op == '+' else 'вычитать'
                raise FormulaError(f'Нельзя {verb} {unit_text(a.units)} и {unit_text(b.units)}.')
            a = Value(a.value + b.value if op == '+' else a.value - b.value, a.units, [*a.parts, {'op': op}, *b.parts])
        return a

    result = total()
    if state['i'] < len(blocks):
        raise FormulaError('Лишняя закрывающая скобка «)».' if is_op(at(), ')') else 'Между блоками не хватает знака.')
    if not state['bare'] and result.units != RUB:
        raise FormulaError(f'В итоге получается {unit_text(result.units)}, а нужны рубли.')
    return result, state['bare']


def rate_block(blocks, units_of_number):
    """The formula's tariff (2026-11-25): a number in ₽ per one unit that multiplies the whole formula — no «+» / «−»
    outside the brackets, and it is not divided by. «(Гкал − Гкал на воду) × Тариф» → Тариф; «Абонплата + Расход ×
    Тариф» → None (no single «кол-во × тариф»). Two such numbers — None too."""
    depth, found, prev = 0, [], None
    for block in blocks:
        if block.get('t') == 'op':
            op = block.get('op')
            depth += 1 if op == '(' else -1 if op == ')' else 0
            if depth == 0 and op in ('+', '−'):
                return None
        elif depth == 0 and block.get('t') == 'num' and not (prev and prev.get('op') == '÷'):
            units = units_of_number(block)
            if units.get('₽') == 1 and len(units) == 2 and sorted(units.values()) == [-1, 1]:
                found.append(block)
        prev = block
    return found[0] if len(found) == 1 else None


# ---------- Who pays: follows from the meter blocks ----------

def meter_blocks(blocks):
    return [block for block in blocks if block.get('t') == 'meter']


MIXED = 'Общий счётчик и счётчики арендаторов в одной формуле нельзя — для общего сделайте отдельную услугу.'


def check_mixed(blocks, owner_of):
    """Common meters and tenants' meters in one formula (2026-11-21: refused, as in «По счётчикам»). Blocks
    «складываем» are one number for all — not counted here."""
    whose = {owner_of(pk) is not None for block in meter_blocks(blocks) if block.get('join') != 'sum'
             for pk in block.get('meters') or []}
    if whose == {True, False}:
        raise FormulaError(MIXED)


def _tenants_in(blocks, owner_of):
    """The tenants whose meters stand in the formula — single meters and «Σ» blocks alike («складываем» — the whole
    object's number — not counted), in the formula's order."""
    found = []
    for block in meter_blocks(blocks):
        if block.get('join') == 'sum':
            continue
        for pk in block.get('meters') or []:
            tenant = owner_of(pk)
            if tenant and tenant not in found:
                found.append(tenant)
    return found


def mode(blocks, owner_of):
    """'each' — every tenant pays by his own meters (a tenant's meter stands in the formula, alone or in a «Σ» block);
    'total' — one sum for the object, split by «Делим»."""
    return 'each' if _tenants_in(blocks, owner_of) else 'total'


def payers(blocks, owner_of, tenant_ids):
    """In the 'each' mode: who pays — every tenant with a meter of his in the formula (2026-11-22: a «Σ» block is only a
    short way to write «сч1 + сч2 + сч3»). Common and tenants' meters together are refused."""
    check_mixed(blocks, owner_of)
    named = _tenants_in(blocks, owner_of)
    return [tenant for tenant in tenant_ids if tenant in named]


def meter_usage(block, tenant, usage_of, owner_of):
    """The month's usage a meter block stands for: one meter — its usage, or 0 in another tenant's count;
    «складываем» or the whole object — the sum; «у каждого свой» — the tenant's own meters."""
    meters = block.get('meters') or []
    if len(meters) == 1:
        if is_foreign(block, tenant, owner_of):
            return Decimal('0')
        return usage_of(meters[0])
    if tenant is None or block.get('join') == 'sum':
        return sum((usage_of(pk) for pk in meters), Decimal('0'))
    return sum((usage_of(pk) for pk in meters if owner_of(pk) == tenant), Decimal('0'))


def is_foreign(block, tenant, owner_of):
    """Another tenant's meter (or a «Σ» block with none of his), in this tenant's count: 0, left out of his bill line."""
    meters = block.get('meters') or []
    if tenant is None or not meters or block.get('join') == 'sum':
        return False
    if len(meters) > 1:  # a «Σ» block with none of his meters
        return not any(owner_of(pk) == tenant for pk in meters)
    owner = owner_of(meters[0])
    return owner is not None and owner != tenant


def drop_foreign(parts):
    """The bill line without another tenant's meters (each was a 0): «(4 м³ + 0 м³) × 45 ₽» → «4 м³ × 45 ₽».
    A part marked 'foreign' goes with the «+» / «−» next to it; brackets left around one value go too."""
    out = list(parts)
    while True:
        at = next((i for i, part in enumerate(out) if part.get('foreign')), None)
        if at is None:
            break
        if at > 0 and out[at - 1].get('op') in ('+', '−'):
            del out[at - 1:at + 1]
        elif at + 1 < len(out) and out[at + 1].get('op') == '+':
            del out[at:at + 2]
        else:
            out[at] = dict(out[at], foreign=False)
    changed = True
    while changed:
        changed = False
        for i in range(len(out) - 2):
            if out[i].get('op') == '(' and 'op' not in out[i + 1] and out[i + 2].get('op') == ')':
                del out[i + 2], out[i]
                changed = True
                break
    return out


def clean_blocks(raw, number_ids, meter_ids):
    """The blocks as posted by the formula window, keeping only what is known: numbers of this service, meters of
    this object, the six signs."""
    blocks = []
    for block in raw if isinstance(raw, list) else []:
        if not isinstance(block, dict):
            continue
        kind = block.get('t')
        if kind == 'op' and block.get('op') in SIGNS:
            blocks.append({'t': 'op', 'op': block['op']})
        elif kind == 'num' and block.get('id') in number_ids:
            blocks.append({'t': 'num', 'id': block['id']})
        elif kind == 'meter':
            meters = [pk for pk in block.get('meters') or [] if pk in meter_ids]
            key = str(block.get('key') or '')[:120]
            blocks.append({'t': 'meter', 'key': key, 'meters': meters,
                           'join': 'sum' if block.get('join') == 'sum' else 'each'})
    return blocks
