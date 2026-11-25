"""«Настроить счёт» (2026-11-25): each tenant's own bill — plain or with requisites, VAT, «Оплатить до», and a
coefficient for each service (× that line of this tenant's bill only)."""

import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.http import QueryDict
from django.test import TestCase
from django.urls import reverse

from apps.properties.models import Property
from apps.tenants.models import Tenant

from . import services
from .models import Receipt, TenantCoefficient

OCT = datetime.date(2026, 10, 1)


def form(**values):
    data = QueryDict(mutable=True)
    for key, value in values.items():
        data[key] = value
    return data


class BillSettingsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='b@example.ru', email='b@example.ru', password='secret1')
        self.prop = Property.objects.create(owner=self.user, name='Счёт 1', area=Decimal('60'))
        self.viktor = Tenant.objects.create(property=self.prop, name='Виктор', share_percent=Decimal('45'))
        self.vlad = Tenant.objects.create(property=self.prop, name='Владислав', share_percent=Decimal('55'))
        self.cleaning = Receipt.objects.create(property=self.prop, name='Уборка', provider='ООО «Чисто»',
                                               amount_mode=Receipt.AmountMode.FIXED, fixed_amount=Decimal('1000'))

    def totals(self):
        bill = services.month_bill(self.prop, OCT)
        return {p.tenant.name: p.total for p in bill.payers}, bill

    def test_coefficient_only_for_that_tenant_and_only_when_on(self):
        TenantCoefficient.objects.create(tenant=self.viktor, receipt=self.cleaning, value=Decimal('1.2'))
        self.assertEqual(self.totals()[0], {'Виктор': Decimal('450.00'), 'Владислав': Decimal('550.00')})  # off
        self.viktor.coef_on = True
        self.viktor.save()
        totals, bill = self.totals()
        self.assertEqual(totals, {'Виктор': Decimal('540.00'), 'Владислав': Decimal('550.00')})
        self.assertEqual(sum((line.amount for line in bill.owner.lines), Decimal('0')), 0)  # the owner — without it

    def test_vat_included_and_on_top(self):
        payer = self.totals()[1].payers[0]
        self.assertIsNone(services.bill_vat(payer))  # a plain bill
        tenant = payer.tenant
        tenant.bill_requisites, tenant.vat, tenant.vat_rate = True, 'in', 22
        self.assertEqual(services.bill_vat(payer), {'mode': 'in', 'rate': '22', 'vat': Decimal('81.15'),
                                                    'net': Decimal('368.85'), 'pay': Decimal('450.00')})
        tenant.vat = 'top'
        self.assertEqual(services.bill_vat(payer)['pay'], Decimal('549.00'))

    def test_save_checks_inn_and_keeps_coefficients(self):
        errors = services.save_bill_settings(self.viktor, form(requisites='1', legal_name='ООО «Виктор»', inn='123'))
        self.assertIn('inn', errors)
        errors = services.save_bill_settings(self.viktor, form(
            requisites='1', legal_name='ООО «Виктор»', inn='7802 123 456', kpp='', vat='top', vat_rate='7',
            due_on='1', due_day='15', coef_on='1', **{f'k-{self.cleaning.pk}': '1,25'}))
        self.assertEqual(errors, {})
        self.viktor.refresh_from_db()
        self.assertEqual((self.viktor.inn, self.viktor.vat, self.viktor.vat_rate, self.viktor.due_day, self.viktor.coef_on),
                         ('7802123456', 'top', 7, 15, True))
        self.assertEqual(TenantCoefficient.objects.get(tenant=self.viktor).value, Decimal('1.25'))
        # back to 1 — the coefficient row goes; a plain bill — no VAT
        services.save_bill_settings(self.viktor, form(requisites='0', vat='top', **{f'k-{self.cleaning.pk}': '1'}))
        self.viktor.refresh_from_db()
        self.assertEqual(self.viktor.vat, 'none')
        self.assertFalse(TenantCoefficient.objects.exists())

    def test_window_opens_and_saves_back_to_the_page(self):
        self.client.force_login(self.user)
        url = reverse('bill_settings', args=[self.viktor.pk])
        page = self.client.get(url, HTTP_X_MODAL='1')
        self.assertContains(page, 'Счёт · Виктор')
        self.assertContains(page, 'Уборка')
        back = reverse('property_detail', args=[self.prop.pk])
        response = self.client.post(url, {'requisites': '0', 'due_on': '1', 'due_day': '10'}, HTTP_X_MODAL='1',
                                    HTTP_REFERER='http://testserver' + back)
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response['X-Modal-Redirect'], back)

    def test_someone_elses_tenant_is_not_found(self):
        other = User.objects.create_user(username='o@example.ru', email='o@example.ru', password='secret1')
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse('bill_settings', args=[self.viktor.pk])).status_code, 404)
