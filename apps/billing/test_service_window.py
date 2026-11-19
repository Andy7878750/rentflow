"""The service window of 2026-11-19: the meter's own tariff, a common meter divided between the tenants, «По тарифу»
with any unit, and its save endpoint."""

import datetime
import json
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.properties.models import Property
from apps.tenants.models import Tenant

from . import services
from .models import Meter, MeterTariff, Receipt

OCT, NOV = datetime.date(2026, 10, 1), datetime.date(2026, 11, 1)


class MeterTariffTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='w@example.ru', email='w@example.ru', password='secret1')
        self.prop = Property.objects.create(owner=self.user, name='Королева 61', area=Decimal('60'))
        self.viktor = Tenant.objects.create(property=self.prop, name='Виктор', share_percent=Decimal('45'),
                                            area=Decimal('27'))
        self.vlad = Tenant.objects.create(property=self.prop, name='Владислав', share_percent=Decimal('55'),
                                          area=Decimal('33'))

    def meter(self, tenant=None, **extra):
        meter = Meter.objects.create(property=self.prop, kind='water', name='Вода холодная', unit='м³', tenant=tenant,
                                     serial='545575', **extra)
        services.save_meter_tariff(meter, Decimal('10'), None, today=datetime.date(2026, 10, 5))
        return meter

    def service(self, *meters):
        receipt = services.new_receipt(self.prop, 'water')
        receipt.metered = True
        return services.save_receipt(receipt, meter_ids=[m.pk for m in meters], tariffs={})

    def read(self, month, meter, prev, cur):
        services.save_month_input(self.prop, month, {f'prev-{meter.pk}': prev, f'cur-{meter.pk}': cur})

    def totals(self, month):
        bill = services.month_bill(self.prop, month)
        return ({p.tenant.name: sum(line.amount for line in p.lines) for p in bill.payers},
                sum((line.amount for line in bill.owner.lines), Decimal('0')))

    def test_tenant_meter_by_its_own_tariff(self):
        meter = self.meter(self.viktor)
        self.service(meter)
        self.read(OCT, meter, '100', '110')
        self.assertEqual(self.totals(OCT)[0]['Виктор'], Decimal('100.00'))

    def test_new_tariff_from_this_month_old_months_keep_theirs(self):
        meter = self.meter(self.viktor)
        self.service(meter)
        self.read(OCT, meter, '100', '110')
        services.save_meter_tariff(meter, Decimal('12'), None, today=datetime.date(2026, 11, 3))
        self.read(NOV, meter, '110', '120')
        self.assertEqual(self.totals(OCT)[0]['Виктор'], Decimal('100.00'))
        self.assertEqual(self.totals(NOV)[0]['Виктор'], Decimal('120.00'))
        self.assertEqual(MeterTariff.objects.filter(meter=meter).count(), 2)

    def test_common_meter_divided_by_shares(self):
        meter = self.meter(split='shares')
        receipt = self.service(meter)
        self.assertEqual(receipt.split, Receipt.Split.METERS)
        self.read(OCT, meter, '100', '110')
        self.assertEqual(self.totals(OCT), ({'Виктор': Decimal('45.00'), 'Владислав': Decimal('55.00')}, 0))

    def test_common_meter_tenant_off_owner_takes_or_passes_on(self):
        meter = self.meter(split='shares')
        meter.excluded.set([self.vlad])
        self.service(meter)
        self.read(OCT, meter, '100', '110')
        self.assertEqual(self.totals(OCT), ({'Виктор': Decimal('45.00'), 'Владислав': 0}, Decimal('55.00')))
        meter.owner_takes = False
        meter.save()
        self.assertEqual(self.totals(OCT), ({'Виктор': Decimal('100.00'), 'Владислав': 0}, 0))

    def test_tenant_and_common_meters_in_one_service(self):
        own = self.meter(self.viktor)
        common = self.meter(split='equal')
        self.service(own, common)
        self.read(OCT, own, '0', '5')
        self.read(OCT, common, '0', '10')
        self.assertEqual(self.totals(OCT), ({'Виктор': Decimal('100.00'), 'Владислав': Decimal('50.00')}, 0))

    def test_rate_with_own_unit_and_volume(self):
        receipt = services.new_receipt(self.prop, 'custom')
        receipt.name, receipt.amount_mode, receipt.split = 'Вывоз мусора', Receipt.AmountMode.RATE, Receipt.Split.SHARES
        receipt.rate, receipt.rate_unit, receipt.volume = Decimal('20'), 'м³', Decimal('5')
        receipt = services.save_receipt(receipt)
        self.assertEqual(services.rate_total(receipt, OCT), (Decimal('100.00'), '5\xa0м³ × 20\xa0₽'))
        self.assertEqual(receipt.split, Receipt.Split.SHARES)

    def test_rate_square_metres_without_volume_take_the_area(self):
        receipt = services.new_receipt(self.prop, 'custom')
        receipt.name, receipt.amount_mode = 'Уборка', Receipt.AmountMode.RATE
        receipt.rate, receipt.rate_unit = Decimal('2'), 'м²'
        receipt = services.save_receipt(receipt)
        self.assertEqual(services.rate_total(receipt, OCT)[0], Decimal('120.00'))
