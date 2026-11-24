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

    def test_common_meter_payer_text_as_it_is_divided(self):
        tenants = [self.viktor, self.vlad]
        meter = self.meter(split='shares')
        self.assertEqual(services.meter_payer_text(meter, tenants), 'Общий · Виктор 45% · Владислав 55%')
        meter.split = 'area'
        self.assertEqual(services.meter_payer_text(meter, tenants), 'Общий · по м² · Виктор 27\xa0м² · Владислав 33\xa0м²')
        meter.excluded.set([self.vlad])
        self.assertEqual(services.meter_payer_text(meter, tenants), 'Общий · по м² · Виктор 27\xa0м² · вы 33\xa0м²')
        meter.owner_takes = False  # Виктор pays for it all — the whole 60 м²
        self.assertEqual(services.meter_payer_text(meter, tenants), 'Общий · по м² · Виктор 60\xa0м²')
        meter.owner_takes = True
        meter.split = 'equal'
        self.assertEqual(services.meter_payer_text(meter, tenants), 'Общий · поровну · Виктор 1/2 · вы 1/2')

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


class ServiceWindowViewTests(TestCase):
    """The window itself: drawn from the state, every change saved as one service (JSON)."""

    setUp = MeterTariffTests.setUp
    meter = MeterTariffTests.meter

    def post(self, **data):
        self.client.force_login(self.user)
        return self.client.post(reverse('service_save', args=[self.prop.pk]), json.dumps(data),
                                content_type='application/json')

    def test_window_opens_with_the_state(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('service_window', args=[self.prop.pk]), HTTP_X_MODAL='1')
        self.assertContains(response, 'id="svc-state"')
        self.assertContains(response, 'Услуги <span>· Королева 61</span>')

    def test_new_fixed_service_with_one_tenant_off_and_the_rest_passed_on(self):
        response = self.post(name='Интернет', provider='Ростелеком', mode='fixed', fixed='1 000', split='shares',
                             excluded=[self.vlad.pk], owner_takes=False)
        self.assertEqual(response.status_code, 200)
        receipt = Receipt.objects.get(property=self.prop)
        self.assertEqual((receipt.amount_mode, receipt.fixed_amount, receipt.owner_takes),
                         (Receipt.AmountMode.FIXED, Decimal('1000'), False))
        self.assertEqual(list(receipt.excluded.all()), [self.vlad])
        self.assertEqual(response.json()['selected'], receipt.pk)

    def test_no_name_no_service(self):
        response = self.post(name=' ', provider='УК', mode='receipt')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Receipt.objects.exists())

    def test_no_supplier_no_service(self):
        response = self.post(name='Ком. услуги', provider=' ', mode='receipt')
        self.assertEqual((response.status_code, response.json()['error']), (400, 'Введите поставщика.'))
        self.assertFalse(Receipt.objects.exists())

    def test_by_meters_one_kind_who_pays_and_input_by_each(self):
        own, common = self.meter(), self.meter()
        light = Meter.objects.create(property=self.prop, kind='electricity', name='Электричество', serial='1')
        response = self.post(name='Вода', provider='Водоканал', mode='meters', group='water', meters=[
            {'id': own.pk, 'who': self.viktor.pk, 'input': 'usage'},
            {'id': common.pk, 'who': 'common', 'split': 'equal', 'excluded': [self.vlad.pk], 'owner_takes': False},
        ])
        self.assertEqual(response.status_code, 200)
        receipt = Receipt.objects.get(property=self.prop)
        self.assertEqual((receipt.metered, receipt.split, receipt.kind), (True, Receipt.Split.METERS, 'water'))
        # Only the meters of the chosen kind: the electricity meter stays out.
        self.assertEqual(set(receipt.meters.all()), {own, common})
        own.refresh_from_db()
        common.refresh_from_db()
        self.assertEqual((own.tenant, own.input_mode), (self.viktor, 'usage'))
        self.assertEqual((common.split, common.owner_takes, list(common.excluded.all())), ('equal', False, [self.vlad]))
        groups = {g['key']: g['meters'] for g in response.json()['groups']}
        self.assertEqual(groups, {'water': [own.pk, common.pk], 'electricity': [light.pk]})
        # The same kind can't go into a second service.
        response = self.post(name='Ещё', provider='Водоканал', mode='meters', group='water',
                             meters=[{'id': own.pk, 'who': 'owner'}, {'id': common.pk, 'who': 'owner'}])
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Receipt.objects.filter(name='Ещё').exists())

    def test_by_usage_the_receipt_divided_by_the_meters(self):
        # «По расходу» (2026-11-23): the receipt's sum in proportion to each meter's usage, no tariff.
        first = Meter.objects.create(property=self.prop, kind='electricity', name='Электричество', serial='1', unit='кВт·ч')
        second = Meter.objects.create(property=self.prop, kind='electricity', name='Электричество', serial='2', unit='кВт·ч')
        response = self.post(name='Электричество', provider='ПСК', mode='usage', group='electricity', meters=[
            {'id': first.pk, 'who': self.viktor.pk}, {'id': second.pk, 'who': self.vlad.pk, 'input': 'usage'}])
        self.assertEqual(response.status_code, 200)
        receipt = Receipt.objects.get(property=self.prop)
        self.assertEqual((receipt.metered, receipt.split, receipt.amount_mode), (False, Receipt.Split.USAGE, 'monthly'))
        self.assertEqual(set(receipt.meters.all()), {first, second})
        state = next(s for s in response.json()['services'] if s['id'] == receipt.pk)
        self.assertEqual((state['mode'], state['group']), ('usage', 'electricity'))
        services.save_month_input(self.prop, OCT, {
            f'amount-{receipt.pk}': '17 868,08', f'prev-{first.pk}': '0', f'cur-{first.pk}': '800',
            f'use-{second.pk}': '577,728'})
        bill = services.month_bill(self.prop, OCT)
        self.assertEqual({p.tenant.name: sum(line.amount for line in p.lines) for p in bill.payers},
                         {'Виктор': Decimal('10375.39'), 'Владислав': Decimal('7492.69')})
        self.assertEqual(sum((line.amount for line in bill.owner.lines), Decimal('0')), 0)
        payer = bill.payer_for(self.viktor.pk)
        self.assertEqual([g['title'] for g in services.bill_groups(payer)], ['По счётчикам'])
        # «Общий» is not offered here: a common meter has to get a payer
        response = self.post(id=receipt.pk, name='Электричество', provider='ПСК', mode='usage', group='electricity',
                             meters=[{'id': first.pk, 'who': 'common'}, {'id': second.pk, 'who': self.vlad.pk}])
        self.assertEqual(response.status_code, 400)

    def test_a_meter_switched_off_is_free_for_another_service(self):
        # 2026-11-24: a meter of the group can be switched off — it is not in the service and not counted; another
        # service of the same kind (its own receipt) can take it. At least one meter has to be on.
        first, second = self.meter(), self.meter()
        response = self.post(name='Вода', provider='Водоканал', mode='usage', group='water',
                             meters=[{'id': first.pk, 'who': self.viktor.pk}])
        self.assertEqual(response.status_code, 200)
        receipt = Receipt.objects.get(name='Вода')
        self.assertEqual(list(receipt.meters.all()), [first])
        second.refresh_from_db()
        self.assertEqual((second.tenant, second.vacant), (None, False))  # outside every service — «Общий», not counted
        response = self.post(name='Вода 2', provider='Водоканал', mode='usage', group='water',
                             meters=[{'id': second.pk, 'who': self.vlad.pk}])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(Receipt.objects.get(name='Вода 2').meters.all()), [second])
        # a meter taken by the other service can't be switched on here
        response = self.post(id=receipt.pk, name='Вода', provider='Водоканал', mode='usage', group='water',
                             meters=[{'id': first.pk, 'who': self.viktor.pk}, {'id': second.pk, 'who': self.vlad.pk}])
        self.assertEqual(response.status_code, 400)
        # all off — nothing to save
        response = self.post(id=receipt.pk, name='Вода', provider='Водоканал', mode='usage', group='water', meters=[])
        self.assertEqual((response.status_code, response.json()['error']), (400, 'Выберите счётчики.'))

    def test_by_meters_every_meter_needs_who_pays(self):
        first, second = self.meter(), self.meter()
        response = self.post(name='Вода', provider='Водоканал', mode='meters', group='water',
                             meters=[{'id': first.pk, 'who': self.viktor.pk}, {'id': second.pk, 'who': ''}])
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Receipt.objects.exists())

    def test_tariff_service_with_its_own_unit(self):
        self.post(name='Вывоз мусора', provider='Эколайн', mode='area', rate='13,37', unit='кг', volume='10', split='equal')
        receipt = Receipt.objects.get(property=self.prop)
        self.assertEqual((receipt.rate_unit, receipt.volume), ('кг', Decimal('10')))
        self.assertEqual(services.rate_total(receipt, OCT)[0], Decimal('133.70'))
