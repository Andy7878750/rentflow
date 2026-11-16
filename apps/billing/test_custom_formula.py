"""«Своя формула»: the evaluator (formula.py) and the service counted in month_bill — the mockup's examples."""

import datetime
import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.properties.models import Property
from apps.tenants.models import Tenant

from . import formula as fx
from . import services
from .models import FormulaValue, Meter, Reading, Receipt

User = get_user_model()
SEPT = datetime.date(2026, 9, 1)
OCT = datetime.date(2026, 10, 1)


def num(value, unit='', per=''):
    return fx.Value(Decimal(value), fx.units_of(unit, per), [{'value': Decimal(value), 'unit': unit}])


class EvaluatorTests(SimpleTestCase):
    """The parser over plain values: signs, brackets, units."""

    def run_formula(self, *tokens):
        values = {}
        blocks = []
        for token in tokens:
            if isinstance(token, str) and token in fx.SIGNS:
                blocks.append({'t': 'op', 'op': token})
            else:
                values[len(blocks)] = token
                blocks.append({'t': 'num', 'id': len(blocks)})
        return fx.evaluate(blocks, lambda block: values[block['id']])

    def test_brackets_and_order(self):
        result, bare = self.run_formula(
            '(', num('0.42', 'Гкал'), '−', '(', num('5', 'м³'), '×', num('0.06', 'Гкал', 'м³'), ')', ')', '×',
            num('4800', '₽', 'Гкал'))
        self.assertEqual(result.value, Decimal('576.0000'))
        self.assertFalse(bare)

    def test_result_must_be_rubles(self):
        with self.assertRaisesMessage(fx.FormulaError, 'В итоге получается м³, а нужны рубли.'):
            self.run_formula(num('3', 'м³'), '+', num('2', 'м³'))

    def test_no_adding_different_units(self):
        with self.assertRaisesMessage(fx.FormulaError, 'Нельзя складывать ₽ и м³.'):
            self.run_formula(num('3', '₽'), '+', num('2', 'м³'))

    def test_a_bare_number_switches_the_check_off(self):
        result, bare = self.run_formula(num('3', 'м³'), '×', num('45'))
        self.assertTrue(bare)
        self.assertEqual(result.value, Decimal('135'))

    def test_broken_formulas_say_why(self):
        cases = [
            (('×', num('1', '₽')), 'Знак «×» стоит не на месте.'),
            ((num('1', '₽'), '×'), 'Формула обрывается'),
            (('(', num('1', '₽')), 'Не хватает закрывающей скобки'),
            ((num('1', '₽'), ')'), 'Лишняя закрывающая скобка'),
            ((num('1', '₽'), num('1', '₽')), 'Между блоками не хватает знака.'),
            ((num('1', '₽'), '÷', num('0', '')), 'Делим на ноль'),
        ]
        for tokens, message in cases:
            with self.subTest(message=message), self.assertRaisesMessage(fx.FormulaError, message):
                self.run_formula(*tokens)


class FormulaServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='f@example.ru', email='f@example.ru', password='secret1')
        self.prop = Property.objects.create(owner=self.user, name='Королева 61', area=Decimal('110'))
        self.viktor = Tenant.objects.create(property=self.prop, name='Виктор', share_percent=Decimal('55'), area=Decimal('60.5'))
        self.vlad = Tenant.objects.create(property=self.prop, name='Владислав', share_percent=Decimal('45'), area=Decimal('49.5'))
        self.meters = {}
        usage = {'electricity': (800, 500), 'water': (3, 2), 'hot_water': (1, 4)}
        units = {'electricity': 'кВт·ч', 'water': 'м³', 'hot_water': 'м³'}
        for kind, (v, l) in usage.items():
            for tenant, value in ((self.viktor, v), (self.vlad, l)):
                meter = Meter.objects.create(property=self.prop, tenant=tenant, kind=kind, name=kind, unit=units[kind],
                                             input_mode=Receipt.InputMode.USAGE)
                Reading.objects.create(meter=meter, month=SEPT, usage=Decimal(value))
                self.meters[kind, tenant.pk] = meter

    def ids(self, kind):
        return [self.meters[kind, self.viktor.pk].pk, self.meters[kind, self.vlad.pk].pk]

    def make(self, numbers, blocks, split=Receipt.Split.SHARES, owners=None):
        receipt = services.new_receipt(self.prop, 'custom')
        receipt.name, receipt.amount_mode, receipt.split = 'Своя', Receipt.AmountMode.FORMULA, split
        data = {'numbers': numbers, 'blocks': blocks, 'owners': owners or {}}
        self.assertEqual(services.formula_problem(self.prop, data), '')
        return services.save_receipt(receipt, formula=data, today=datetime.date(2026, 9, 10))

    def line(self, bill, tenant, receipt):
        payer = bill.payer_for(tenant.pk)
        return next((line for line in payer.lines if line.receipt.pk == receipt.pk), None)

    @staticmethod
    def op(sign):
        return {'t': 'op', 'op': sign}

    def meter(self, kind, join='each', meters=None):
        return {'t': 'meter', 'key': kind, 'meters': meters if meters is not None else self.ids(kind), 'join': join}

    def test_sewage_each_by_own_meters(self):
        """(Вода гор. + Вода хол.) × 45 ₽/м³ — each by his own meters."""
        receipt = self.make(
            [{'id': 'n1', 'label': 'Тариф водоотведения', 'unit': '₽', 'per': 'м³', 'value': '45'}],
            [self.op('('), self.meter('hot_water'), self.op('+'), self.meter('water'), self.op(')'), self.op('×'),
             {'t': 'num', 'id': 'n1'}])
        self.assertEqual(receipt.split, Receipt.Split.METERS)
        self.assertEqual(receipt.meters.count(), 4)
        bill = services.month_bill(self.prop, SEPT)
        self.assertEqual(self.line(bill, self.viktor, receipt).amount, Decimal('180.00'))
        self.assertEqual(self.line(bill, self.vlad, receipt).amount, Decimal('270.00'))
        self.assertEqual(self.line(bill, self.viktor, receipt).formula.replace(services.NBSP, ' '), '(1 м³ + 3 м³) × 45 ₽/м³')

    def test_sum_by_usage(self):
        """Сумма по квитанции ÷ Электричество · все вместе × Электричество · у каждого (ПЕСК)."""
        receipt = self.make(
            [{'id': 'n1', 'label': 'Сумма по квитанции', 'monthly': True, 'unit': '₽'}],
            [{'t': 'num', 'id': 'n1'}, self.op('÷'), self.meter('electricity', 'sum'), self.op('×'), self.meter('electricity')])
        bill = services.month_bill(self.prop, SEPT)
        self.assertIsNone(self.line(bill, self.viktor, receipt))  # the sum isn't typed yet
        self.assertIn(receipt, bill.missing)
        number = receipt.numbers.get()
        services.save_month_input(self.prop, SEPT, {f'fnum-{number.pk}': '8 450'})
        self.assertEqual(FormulaValue.objects.get(number=number).value, Decimal('8450'))
        bill = services.month_bill(self.prop, SEPT)
        self.assertEqual(self.line(bill, self.viktor, receipt).amount, Decimal('5200.00'))
        self.assertEqual(self.line(bill, self.vlad, receipt).amount, Decimal('3250.00'))

    def test_heating_one_sum_split_by_shares(self):
        """(Тепло − Вода гор. · все вместе × Подогрев) × Тариф — one sum for the object, by shares."""
        receipt = self.make(
            [{'id': 'n1', 'label': 'Тепло по квитанции', 'monthly': True, 'unit': 'Гкал'},
             {'id': 'n2', 'label': 'Подогрев 1 м³', 'unit': 'Гкал', 'per': 'м³', 'value': '0,06'},
             {'id': 'n3', 'label': 'Тариф тепла', 'unit': '₽', 'per': 'Гкал', 'value': '4800'}],
            [self.op('('), {'t': 'num', 'id': 'n1'}, self.op('−'), self.op('('), self.meter('hot_water', 'sum'),
             self.op('×'), {'t': 'num', 'id': 'n2'}, self.op(')'), self.op(')'), self.op('×'), {'t': 'num', 'id': 'n3'}])
        self.assertEqual(receipt.split, Receipt.Split.SHARES)
        heat = receipt.numbers.get(label='Тепло по квитанции')
        services.save_month_input(self.prop, SEPT, {f'fnum-{heat.pk}': '0,42'})
        bill = services.month_bill(self.prop, SEPT)
        entry = next(entry for entry in bill.entries if entry.receipt.pk == receipt.pk)
        self.assertEqual(entry.total, Decimal('576.00'))
        self.assertEqual(self.line(bill, self.viktor, receipt).amount, Decimal('316.80'))
        self.assertEqual(self.line(bill, self.vlad, receipt).amount, Decimal('259.20'))

    def test_only_one_tenant(self):
        """One tenant's meter × tariff — the formula is his only."""
        receipt = self.make(
            [{'id': 'n1', 'label': 'Тариф', 'unit': '₽', 'per': 'кВт·ч', 'value': '9,6'}],
            [self.meter('electricity', meters=[self.meters['electricity', self.viktor.pk].pk]), self.op('×'),
             {'t': 'num', 'id': 'n1'}])
        bill = services.month_bill(self.prop, SEPT)
        self.assertEqual(self.line(bill, self.viktor, receipt).amount, Decimal('7680.00'))
        self.assertIsNone(self.line(bill, self.vlad, receipt))

    def test_meters_of_another_service_are_not_typed_again(self):
        """«Экология» = (Вода хол. + Вода гор.) × тариф: the water services type the readings; the formula just takes them."""
        water = services.new_receipt(self.prop, 'water')
        services.save_receipt(water, meter_ids=self.ids('water'), tariffs={})
        hot = self.ids('hot_water')  # in no service — common now; seated in the formula's meter window
        receipt = self.make(
            [{'id': 'n1', 'label': 'Тариф', 'unit': '₽', 'per': 'м³', 'value': '50'}],
            [self.op('('), self.meter('water'), self.op('+'), self.meter('hot_water'), self.op(')'), self.op('×'),
             {'t': 'num', 'id': 'n1'}],
            owners={str(hot[0]): str(self.viktor.pk), str(hot[1]): str(self.vlad.pk)})
        bill = services.month_bill(self.prop, SEPT)
        entry = next(entry for entry in bill.entries if entry.receipt.pk == receipt.pk)
        self.assertEqual(entry.shared_services, ['Вода холодная'])
        self.assertEqual({meter.kind for meter, _ in entry.readings}, {'hot_water'})  # only its own meters to type
        self.assertEqual(self.line(bill, self.vlad, receipt).amount, Decimal('300.00'))  # (2 + 4) × 50

    def test_switched_off_tenant_leaves_his_part_to_the_owner(self):
        receipt = self.make(
            [{'id': 'n1', 'label': 'Тариф', 'unit': '₽', 'per': 'кВт·ч', 'value': '2'}],
            [self.meter('electricity'), self.op('×'), {'t': 'num', 'id': 'n1'}])
        receipt.excluded.set([self.vlad])
        bill = services.month_bill(self.prop, SEPT)
        self.assertIsNone(self.line(bill, self.vlad, receipt))
        self.assertEqual(bill.owner.total, Decimal('1000.00'))

    def test_a_tariff_keeps_its_history(self):
        data = {'numbers': [{'id': 'n1', 'label': 'Тариф', 'unit': '₽', 'per': 'кВт·ч', 'value': '2'}],
                'blocks': [self.meter('electricity'), self.op('×'), {'t': 'num', 'id': 'n1'}]}
        receipt = services.new_receipt(self.prop, 'custom')
        receipt.name, receipt.amount_mode = 'Свет', Receipt.AmountMode.FORMULA
        receipt = services.save_receipt(receipt, formula=data, today=datetime.date(2026, 9, 10))
        number = receipt.numbers.get()
        data['numbers'] = [{'id': str(number.pk), 'label': 'Тариф', 'unit': '₽', 'per': 'кВт·ч', 'value': '3'}]
        data['blocks'][-1] = {'t': 'num', 'id': str(number.pk)}
        services.save_receipt(receipt, formula=data, today=datetime.date(2026, 10, 5))
        self.assertEqual(receipt.numbers.get().pk, number.pk)  # the same number, a new value
        for month in (SEPT, OCT):
            Reading.objects.get_or_create(meter=self.meters['electricity', self.viktor.pk], month=month,
                                          defaults={'usage': Decimal('800')})
            Reading.objects.get_or_create(meter=self.meters['electricity', self.vlad.pk], month=month,
                                          defaults={'usage': Decimal('500')})
        self.assertEqual(self.line(services.month_bill(self.prop, SEPT), self.viktor, receipt).amount, Decimal('1600.00'))
        self.assertEqual(self.line(services.month_bill(self.prop, OCT), self.viktor, receipt).amount, Decimal('2400.00'))

    def test_problems_before_saving(self):
        el = self.meter('electricity')
        rub = {'id': 'n1', 'label': 'Тариф', 'unit': '₽', 'per': 'м³', 'value': '45'}
        self.assertEqual(services.formula_problem(self.prop, {'numbers': [], 'blocks': []}),
                         'Соберите формулу — нажмите «Собрать формулу».')
        self.assertEqual(
            services.formula_problem(self.prop, {'numbers': [rub], 'blocks': [el, self.op('×'), {'t': 'num', 'id': 'n1'}]}),
            'В итоге получается кВт·ч·₽/м³, а нужны рубли.')
        two = [self.op('('), self.meter('electricity', meters=[self.meters['electricity', self.viktor.pk].pk]), self.op('+'),
               self.meter('electricity', meters=[self.meters['electricity', self.vlad.pk].pk]), self.op(')'), self.op('×'),
               {'t': 'num', 'id': 'n1'}]
        rub['per'] = 'кВт·ч'
        self.assertIn('непонятно, кому выставить', services.formula_problem(self.prop, {'numbers': [rub], 'blocks': two}))

    def test_a_formula_locks_no_meter(self):
        """It only reads meters: «По счётчикам» of the same meter is still possible."""
        self.make([{'id': 'n1', 'label': 'Тариф', 'unit': '₽', 'per': 'кВт·ч', 'value': '2'}],
                  [self.meter('electricity'), self.op('×'), {'t': 'num', 'id': 'n1'}])
        other = services.new_receipt(self.prop, 'electricity')
        self.assertEqual(services.busy_meters(other), {})

    def test_its_meters_keep_their_tenants(self):
        """A meter no «По счётчикам» service uses becomes common — but not one a formula reads."""
        self.make([{'id': 'n1', 'label': 'Тариф', 'unit': '₽', 'per': 'кВт·ч', 'value': '2'}],
                  [self.meter('electricity'), self.op('×'), {'t': 'num', 'id': 'n1'}])
        services.release_free_meters(self.prop)
        self.assertEqual(Meter.objects.get(pk=self.ids('electricity')[0]).tenant_id, self.viktor.pk)
        self.assertIsNone(Meter.objects.get(pk=self.ids('water')[0]).tenant_id)  # not in any service

    def test_service_window_saves_the_formula(self):
        self.client.force_login(self.user)
        data = {'numbers': [{'id': 'n1', 'label': 'Тариф', 'unit': '₽', 'per': 'кВт·ч', 'value': '2'}],
                'blocks': [self.meter('electricity'), self.op('×'), {'t': 'num', 'id': 'n1'}],
                'owners': {str(pk): '' for pk in []}}
        url = reverse('receipt_create', args=[self.prop.pk])
        response = self.client.post(url, {'kind': 'custom', 'name': 'Свет', 'charge': 'formula', 'split': 'shares',
                                          'formula_json': json.dumps(data)})
        self.assertEqual(response.status_code, 302)
        receipt = Receipt.objects.get(name='Свет')
        self.assertEqual(receipt.amount_mode, Receipt.AmountMode.FORMULA)
        self.assertEqual(len(receipt.formula), 3)
        # An empty formula is refused with a sentence, nothing saved.
        response = self.client.post(url, {'kind': 'custom', 'name': 'Пусто', 'charge': 'formula', 'split': 'shares',
                                          'formula_json': '{}'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Соберите формулу')
        self.assertFalse(Receipt.objects.filter(name='Пусто').exists())
