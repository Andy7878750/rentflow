"""«Формула» of the service window (billing.services.formula_example) and its view."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.properties.models import Property
from apps.tenants.models import Tenant

from . import services
from .models import Receipt

User = get_user_model()


class FormulaExampleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='a@example.ru', email='a@example.ru', password='secret1')
        self.prop = Property.objects.create(owner=self.user, name='Королева 61', area=Decimal('60'))
        self.viktor = Tenant.objects.create(
            property=self.prop, name='Виктор', share_percent=Decimal('45'), area=Decimal('27'))
        self.vlad = Tenant.objects.create(
            property=self.prop, name='Владислав', share_percent=Decimal('55'), area=Decimal('33'))

    def example(self, kind, chosen=None, **changes):
        receipt = services.new_receipt(self.prop, kind)
        for name, value in changes.items():
            setattr(receipt, name, value)
        return services.formula_example(services.normalize(receipt), chosen)

    def test_shares_on_a_sample_sum(self):
        formula = self.example('management')
        self.assertEqual((formula.payer, formula.amount), ('Виктор', Decimal('1890.00')))
        self.assertEqual([item[1] for item in formula.steps[0].items], ['Сумма квитанции', '×', 'Доля'])

    def test_pick_another_tenant(self):
        formula = self.example('management', chosen=str(self.vlad.pk))
        self.assertEqual((formula.payer, formula.amount), ('Владислав', Decimal('2310.00')))

    def test_equal_and_area(self):
        self.assertEqual(self.example('garbage').amount, Decimal('2100.00'))
        self.assertEqual(self.example('custom', split=Receipt.Split.AREA).amount, Decimal('1890.00'))

    def test_fixed_sum_is_the_typed_one(self):
        formula = self.example('internet', fixed_amount=Decimal('900'))
        self.assertEqual(formula.amount, Decimal('450.00'))

    def test_own_meter_day_night_with_the_typed_tariffs(self):
        formula = self.example('electricity', zones=2, tariff=Decimal('6.12'), tariff_night=Decimal('3.45'))
        # 120 × 6,12 + 80 × 3,45
        self.assertEqual(formula.amount, Decimal('1010.40'))
        self.assertEqual(len(formula.steps), 1)

    def test_common_meter_then_shares_and_coefficient(self):
        formula = self.example('electricity', layout=Receipt.Layout.COMMON, tariff=Decimal('5'),
                               coefficient=Decimal('1.2'))
        # 120 × 5 = 600; 600 × 45% = 270; × 1,2 = 324
        self.assertEqual([step.result for step in formula.steps], ['600,00\xa0₽', '324,00\xa0₽'])
        self.assertEqual(formula.amount, Decimal('324.00'))

    def test_owner_pays_it_himself(self):
        formula = self.example('capital_repair')
        self.assertEqual((formula.payer, formula.amount), ('Вы', Decimal('4200')))

    def test_tenants_of_a_fixed_sum_get_their_parts(self):
        receipt = services.new_receipt(self.prop, 'internet')
        receipt.metered, receipt.amount_mode, receipt.fixed_amount = False, 'fixed', Decimal('4800')
        receipt.split = 'shares'
        rows = services.payer_preview(services.normalize(receipt))
        self.assertEqual([(r.tenant.name, r.basis, r.amount_text) for r in rows],
                         [('Виктор', '45%', '2 160,00 ₽'), ('Владислав', '55%', '2 640,00 ₽')])
        receipt.split = 'equal'
        self.assertEqual([r.basis for r in services.payer_preview(receipt)], ['÷ 2', '÷ 2'])
        receipt.amount_mode = 'monthly'
        self.assertEqual([r.amount_text for r in services.payer_preview(receipt)], ['', ''], 'no sum known yet')

    def test_view_recounts_the_unsaved_form(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('receipt_formula', args=[self.prop.pk]), {
            'kind': 'internet', 'name': 'Интернет', 'metered': '0', 'amount_mode': 'fixed',
            'fixed_amount': '4800', 'split': 'shares',
        })
        self.assertContains(response, 'class="payer-list')
        self.assertContains(response, '2 640,00 ₽')

    def test_window_lists_the_tenants_instead_of_the_formula(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('receipt_create', args=[self.prop.pk]) + '?kind=management',
                                   HTTP_X_MODAL='1')
        self.assertNotContains(response, 'Пример для')
        self.assertContains(response, 'class="payer-list')
        self.assertContains(response, 'Виктор')


class PayerSwitchTests(TestCase):
    """«Кто платит»: a tenant switched off doesn't pay the service; their part stays with the owner."""

    def setUp(self):
        self.user = User.objects.create_user(username='b@example.ru', email='b@example.ru', password='secret1')
        self.prop = Property.objects.create(owner=self.user, name='Королева 61', area=Decimal('60'))
        self.viktor = Tenant.objects.create(
            property=self.prop, name='Виктор', share_percent=Decimal('45'), area=Decimal('27'))
        self.vlad = Tenant.objects.create(
            property=self.prop, name='Владислав', share_percent=Decimal('55'), area=Decimal('33'))

    def internet(self, split='shares'):
        receipt = services.new_receipt(self.prop, 'internet')
        receipt.metered, receipt.amount_mode, receipt.fixed_amount = False, 'fixed', Decimal('1000')
        receipt.split = split
        return services.save_receipt(receipt, excluded=[self.vlad.pk])

    def test_preview_marks_the_tenant_off(self):
        rows = services.payer_preview(self.internet())
        self.assertEqual([(r.pays, r.amount_text) for r in rows], [(True, '450,00 ₽'), (False, '')])

    def test_equal_divides_between_those_who_pay(self):
        rows = services.payer_preview(self.internet('equal'))
        self.assertEqual((rows[0].basis, rows[0].amount_text), ('÷ 1', '1 000,00 ₽'))

    def test_month_bill_leaves_the_part_with_the_owner(self):
        self.internet()
        bill = services.month_bill(self.prop, date(2026, 11, 1))
        totals = {p.tenant.name: sum(line.amount for line in p.lines) for p in bill.payers}
        self.assertEqual(totals, {'Виктор': Decimal('450.00'), 'Владислав': 0})
        self.assertEqual(sum(line.amount for line in bill.owner.lines), Decimal('550.00'))

    def test_window_saves_the_switches(self):
        self.client.force_login(self.user)
        self.client.post(reverse('receipt_create', args=[self.prop.pk]), {
            'kind': 'internet', 'name': 'Интернет', 'metered': '0', 'amount_mode': 'fixed',
            'fixed_amount': '1000', 'split': 'shares', 'payers_shown': '1', 'pays': [str(self.viktor.pk)],
        })
        receipt = Receipt.objects.get(property=self.prop)
        self.assertEqual(list(receipt.excluded.all()), [self.vlad])

    def test_view_recounts_with_the_switch(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('receipt_formula', args=[self.prop.pk]), {
            'kind': 'internet', 'name': 'Интернет', 'metered': '0', 'amount_mode': 'fixed',
            'fixed_amount': '1000', 'split': 'equal', 'payers_shown': '1', 'pays': [str(self.viktor.pk)],
        })
        self.assertContains(response, 'не платит')
        self.assertContains(response, '1 000,00 ₽')
