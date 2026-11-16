"""«По площади»: a tariff × the object's m² or × the number of people (2026-11-16)."""

import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.properties.models import Property
from apps.tenants.models import Tenant

from . import services
from .models import Receipt

User = get_user_model()
SEPT = datetime.date(2026, 9, 1)
OCT = datetime.date(2026, 10, 1)


class RateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='r@example.ru', email='r@example.ru', password='secret1')
        self.prop = Property.objects.create(owner=self.user, name='Королева 61', area=Decimal('60'))
        self.viktor = Tenant.objects.create(property=self.prop, name='Виктор', share_percent=Decimal('45'), area=Decimal('27'))
        self.vlad = Tenant.objects.create(property=self.prop, name='Владислав', share_percent=Decimal('55'), area=Decimal('33'))

    def add(self, today=datetime.date(2026, 9, 10), **changes):
        receipt = services.new_receipt(self.prop, 'garbage')
        receipt.amount_mode = Receipt.AmountMode.RATE
        for name, value in changes.items():
            setattr(receipt, name, value)
        return services.save_receipt(receipt, today=today)

    def line(self, bill, tenant, receipt):
        return next(line for line in bill.payer_for(tenant.pk).lines if line.receipt.pk == receipt.pk)

    def test_area_times_tariff_split_by_area(self):
        receipt = self.add(rate=Decimal('7.12'), split=Receipt.Split.AREA)
        bill = services.month_bill(self.prop, SEPT)
        entry = next(e for e in bill.entries if e.receipt.pk == receipt.pk)
        self.assertEqual(entry.total, Decimal('427.20'))
        self.assertEqual(entry.rate_text, '60 м² × 7,12 ₽')
        self.assertEqual(self.line(bill, self.viktor, receipt).amount, Decimal('192.24'))
        self.assertEqual(self.line(bill, self.vlad, receipt).amount, Decimal('234.96'))

    def test_people_times_tariff(self):
        receipt = self.add(rate=Decimal('150'), rate_base=Receipt.RateBase.PERSON, persons=3, split=Receipt.Split.EQUAL)
        bill = services.month_bill(self.prop, SEPT)
        self.assertEqual(bill.to_invoice, Decimal('450.00'))
        self.assertEqual(self.line(bill, self.viktor, receipt).amount, Decimal('225.00'))

    def test_no_area_no_sum(self):
        self.prop.area = None
        self.prop.save()
        receipt = self.add(rate=Decimal('7.12'))
        bill = services.month_bill(self.prop, SEPT)
        self.assertIn(receipt, bill.missing)
        self.assertIn('площадь', services.split_warning(receipt))

    def test_a_new_tariff_starts_this_month(self):
        receipt = self.add(rate=Decimal('150'), rate_base=Receipt.RateBase.PERSON, persons=2)
        receipt.persons = 3
        receipt.rate = Decimal('160')
        services.save_receipt(receipt, today=datetime.date(2026, 10, 5))
        sept = services.rate_total(Receipt.objects.get(pk=receipt.pk), SEPT)
        octo = services.rate_total(Receipt.objects.get(pk=receipt.pk), OCT)
        self.assertEqual(sept, (Decimal('300.00'), '2 чел. × 150 ₽'))
        self.assertEqual(octo, (Decimal('480.00'), '3 чел. × 160 ₽'))

    def test_window_saves_and_checks(self):
        self.client.force_login(self.user)
        url = reverse('receipt_create', args=[self.prop.pk])
        base = {'kind': 'garbage', 'name': 'Мусор', 'charge': 'rate', 'rate_base': 'person', 'rate': '150', 'split': 'equal'}
        response = self.client.post(url, base, HTTP_X_MODAL='1')
        self.assertContains(response, 'Укажите, сколько человек.')
        self.client.post(url, {**base, 'persons': '2'}, HTTP_X_MODAL='1')
        receipt = Receipt.objects.get(name='Мусор')
        self.assertEqual((receipt.amount_mode, receipt.rate_base, receipt.rate, receipt.persons),
                         ('rate', 'person', Decimal('150'), 2))
        window = self.client.get(reverse('receipt_edit', args=[receipt.pk]), HTTP_X_MODAL='1')
        self.assertContains(window, 'name="charge" value="rate" checked')
        page = self.client.get(reverse('property_detail', args=[self.prop.pk]))
        self.assertContains(page, '2 чел. × 150 ₽')
