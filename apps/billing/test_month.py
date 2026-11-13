"""Monthly input and the split between tenants (billing.services.month_bill)."""

import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.properties.models import Property
from apps.tenants.models import Tenant

from . import services
from .models import Meter, Reading, Receipt

User = get_user_model()
SEPT = datetime.date(2026, 9, 1)
AUG = datetime.date(2026, 8, 1)


class MonthBillTests(TestCase):
    def setUp(self):
        user = User.objects.create_user(username='a@example.ru', email='a@example.ru', password='secret1')
        self.prop = Property.objects.create(owner=user, name='Королева 61', area=Decimal('60'))
        self.viktor = Tenant.objects.create(
            property=self.prop, name='Виктор', share_percent=Decimal('45'), area=Decimal('27'))
        self.vlad = Tenant.objects.create(
            property=self.prop, name='Владислав', share_percent=Decimal('55'), area=Decimal('33'))

    def add(self, kind, **changes):
        receipt = services.new_receipt(self.prop, kind)
        for name, value in changes.items():
            setattr(receipt, name, value)
        return services.save_receipt(receipt)

    def line(self, bill, tenant, receipt):
        payer = bill.payer_for(tenant.pk)
        return next(line for line in payer.lines if line.receipt.pk == receipt.pk)

    def test_shares(self):
        receipt = self.add('management', name='Содержание и ремонт')
        services.save_month_input(self.prop, SEPT, {f'amount-{receipt.pk}': '4 200'})

        bill = services.month_bill(self.prop, SEPT)

        line = self.line(bill, self.viktor, receipt)
        self.assertEqual(line.amount, Decimal('1890.00'))
        self.assertEqual(line.formula, '4 200,00 ₽ × 45%')
        self.assertEqual(self.line(bill, self.vlad, receipt).amount, Decimal('2310.00'))
        self.assertEqual(bill.to_invoice, Decimal('4200.00'))
        self.assertEqual(bill.owner.total, 0)

    def test_equal_and_rounding_remainder_stays_with_owner(self):
        Tenant.objects.create(property=self.prop, name='Ольга', share_percent=Decimal('0'))
        receipt = self.add('garbage')
        services.save_month_input(self.prop, SEPT, {f'amount-{receipt.pk}': '100'})

        bill = services.month_bill(self.prop, SEPT)

        self.assertEqual([p.total for p in bill.payers], [Decimal('33.33')] * 3)
        self.assertEqual(bill.owner.total, Decimal('0.01'))
        self.assertEqual(bill.to_invoice + bill.owner.total, Decimal('100'))

    def test_area(self):
        receipt = self.add('custom', name='Благоустройство', split=Receipt.Split.AREA)
        services.save_month_input(self.prop, SEPT, {f'amount-{receipt.pk}': '1638'})
        bill = services.month_bill(self.prop, SEPT)
        self.assertEqual(self.line(bill, self.viktor, receipt).amount, Decimal('737.10'))

    def test_unoccupied_share_stays_with_owner(self):
        self.vlad.share_percent = Decimal('30')
        self.vlad.save()
        receipt = self.add('management')
        services.save_month_input(self.prop, SEPT, {f'amount-{receipt.pk}': '1000'})
        bill = services.month_bill(self.prop, SEPT)
        self.assertEqual(bill.to_invoice, Decimal('750.00'))
        self.assertEqual(bill.owner.total, Decimal('250.00'))

    def test_fixed_amount_needs_no_input(self):
        receipt = self.add('custom', name='Охрана', amount_mode=Receipt.AmountMode.FIXED,
                           fixed_amount=Decimal('2000'))
        bill = services.month_bill(self.prop, SEPT)
        self.assertEqual(self.line(bill, self.viktor, receipt).amount, Decimal('900.00'))
        self.assertEqual(bill.missing, [])

    def test_owner_pays_himself(self):
        self.add('capital_repair', amount_mode=Receipt.AmountMode.FIXED, fixed_amount=Decimal('500'))
        bill = services.month_bill(self.prop, SEPT)
        self.assertEqual(bill.to_invoice, 0)
        self.assertEqual(bill.owner.total, Decimal('500'))

    def test_tenant_meters(self):
        receipt = self.add('electricity', tariff=Decimal('6.5'))
        viktor_meter = receipt.meters.get(tenant=self.viktor)
        vlad_meter = receipt.meters.get(tenant=self.vlad)
        services.save_month_input(self.prop, SEPT, {
            f'prev-{viktor_meter.pk}': '1000', f'cur-{viktor_meter.pk}': '1120',
            f'prev-{vlad_meter.pk}': '500', f'cur-{vlad_meter.pk}': '',
        })

        bill = services.month_bill(self.prop, SEPT)
        self.assertEqual(bill.missing, [receipt])
        self.assertEqual((bill.readings_done, bill.readings_total), (1, 2))

        services.save_month_input(self.prop, SEPT, {f'cur-{vlad_meter.pk}': '530'})
        bill = services.month_bill(self.prop, SEPT)
        line = self.line(bill, self.viktor, receipt)
        self.assertEqual(line.amount, Decimal('780.00'))
        self.assertEqual(line.formula, '120 кВт·ч × 6,5 ₽')
        self.assertEqual(self.line(bill, self.vlad, receipt).amount, Decimal('195.00'))

    def test_a_free_meter_is_paid_by_the_owner(self):
        receipt = self.add('electricity', tariff=Decimal('6.5'))
        vlad_meter = receipt.meters.get(tenant=self.vlad)
        vlad_meter.tenant, vlad_meter.vacant = None, True  # Владислав moved out
        vlad_meter.save()
        services.save_month_input(self.prop, SEPT, {
            f'prev-{vlad_meter.pk}': '500', f'cur-{vlad_meter.pk}': '530',
            f'prev-{receipt.meters.get(tenant=self.viktor).pk}': '0',
            f'cur-{receipt.meters.get(tenant=self.viktor).pk}': '0',
        })
        bill = services.month_bill(self.prop, SEPT)
        owner = next(line for line in bill.owner.lines if line.receipt.pk == receipt.pk)
        self.assertEqual(owner.amount, Decimal('195.00'))
        self.assertIn('свободный счётчик', owner.formula)

    def test_previous_reading_comes_from_last_month(self):
        receipt = self.add('water', tariff=Decimal('300'))
        meter = receipt.meters.get(tenant=self.viktor)
        Reading.objects.create(meter=meter, month=AUG, previous=Decimal('10'), current=Decimal('13'))

        bill = services.month_bill(self.prop, SEPT)
        entry = bill.entries[0]
        reading = dict((m.pk, r) for m, r in entry.readings)[meter.pk]
        self.assertEqual(reading.previous, Decimal('13'))
        self.assertIsNone(reading.current)

    def test_common_meter_is_split_by_shares(self):
        receipt = self.add('water', layout=Receipt.Layout.COMMON, tariff=Decimal('310'))
        meter = receipt.meters.get()
        services.save_month_input(self.prop, SEPT, {f'prev-{meter.pk}': '0', f'cur-{meter.pk}': '10'})
        bill = services.month_bill(self.prop, SEPT)
        self.assertEqual(bill.entries[0].total, Decimal('3100.00'))
        self.assertEqual(self.line(bill, self.viktor, receipt).amount, Decimal('1395.00'))

    def test_a_meter_with_its_own_tariff_counts_by_it(self):
        receipt = self.add('water', tariff=Decimal('45.50'))
        hot = receipt.meters.get(tenant=self.viktor)
        hot.name, hot.tariff = 'Вода горячая', Decimal('230')
        hot.save()
        cold = receipt.meters.get(tenant=self.vlad)
        services.save_month_input(self.prop, SEPT, {f'prev-{hot.pk}': '0', f'cur-{hot.pk}': '2',
                                                    f'prev-{cold.pk}': '0', f'cur-{cold.pk}': '2'})
        bill = services.month_bill(self.prop, SEPT)
        self.assertEqual(self.line(bill, self.viktor, receipt).amount, Decimal('460.00'))
        self.assertEqual(self.line(bill, self.vlad, receipt).amount, Decimal('91.00'), 'no own tariff — the service\'s')

    def test_tariff_is_not_taken_from_the_object_page(self):
        receipt = self.add('water', layout=Receipt.Layout.COMMON, tariff=Decimal('300'))
        services.save_month_input(self.prop, SEPT, {f'tariff-{receipt.pk}': '999'})
        self.assertEqual(services.month_bill(self.prop, SEPT).entries[0].tariff, Decimal('300'))

    def test_new_tariff_applies_from_this_month_past_months_keep_the_old(self):
        receipt = self.add('water', layout=Receipt.Layout.COMMON, tariff=Decimal('300'))
        meter = receipt.meters.get()
        services.save_month_input(self.prop, AUG, {f'prev-{meter.pk}': '0', f'cur-{meter.pk}': '10'})
        services.save_month_input(self.prop, SEPT, {f'cur-{meter.pk}': '20'})

        receipt.tariff = Decimal('400')
        services.save_receipt(receipt, today=datetime.date(2026, 9, 15))

        self.assertEqual(services.month_bill(self.prop, AUG).entries[0].total, Decimal('3000.00'))
        self.assertEqual(services.month_bill(self.prop, SEPT).entries[0].total, Decimal('4000.00'))

    def test_usage_is_typed_instead_of_readings(self):
        receipt = self.add('electricity', tariff=Decimal('6.5'), input_mode=Receipt.InputMode.USAGE)
        viktor_meter = receipt.meters.get(tenant=self.viktor)
        vlad_meter = receipt.meters.get(tenant=self.vlad)
        # Readings left over from before don't count: only the typed usage does.
        services.save_month_input(self.prop, SEPT, {
            f'prev-{viktor_meter.pk}': '0', f'cur-{viktor_meter.pk}': '999',
            f'use-{viktor_meter.pk}': '120',
        })
        bill = services.month_bill(self.prop, SEPT)
        self.assertEqual(bill.missing, [receipt])
        self.assertEqual((bill.readings_done, bill.readings_total), (1, 2))

        services.save_month_input(self.prop, SEPT, {f'use-{vlad_meter.pk}': '30'})
        bill = services.month_bill(self.prop, SEPT)
        line = self.line(bill, self.viktor, receipt)
        self.assertEqual(line.amount, Decimal('780.00'))
        self.assertEqual(line.formula, '120 кВт·ч × 6,5 ₽')
        self.assertEqual(self.line(bill, self.vlad, receipt).amount, Decimal('195.00'))

    def test_usage_day_night(self):
        receipt = self.add('electricity', zones=2, tariff=Decimal('7'), tariff_night=Decimal('3'),
                           input_mode=Receipt.InputMode.USAGE, layout=Receipt.Layout.COMMON,
                           split=Receipt.Split.SHARES)
        meter = receipt.meters.get()
        services.save_month_input(self.prop, SEPT, {f'use-{meter.pk}': '10', f'usen-{meter.pk}': '20'})
        bill = services.month_bill(self.prop, SEPT)
        self.assertEqual(bill.entries[0].total, Decimal('130.00'))

    def test_no_meter_resets_input_mode(self):
        receipt = self.add('electricity', input_mode=Receipt.InputMode.USAGE)
        receipt.metered = False
        services.save_receipt(receipt)
        self.assertEqual(receipt.input_mode, Receipt.InputMode.READINGS)

    def test_day_night_meter(self):
        receipt = self.add('electricity', zones=2, tariff=Decimal('7'), tariff_night=Decimal('3'))
        meter = receipt.meters.get(tenant=self.viktor)
        other = receipt.meters.get(tenant=self.vlad)
        services.save_month_input(self.prop, SEPT, {
            f'prev-{meter.pk}': '100', f'cur-{meter.pk}': '110', f'prevn-{meter.pk}': '50', f'curn-{meter.pk}': '70',
            f'prev-{other.pk}': '0', f'cur-{other.pk}': '1',
        })
        self.assertEqual(services.month_bill(self.prop, SEPT).missing, [receipt], 'night reading still missing')

        services.save_month_input(self.prop, SEPT, {f'prevn-{other.pk}': '0', f'curn-{other.pk}': '1'})
        bill = services.month_bill(self.prop, SEPT)
        line = self.line(bill, self.viktor, receipt)
        self.assertEqual(line.amount, Decimal('130.00'))
        self.assertEqual(line.formula, 'день 10 кВт·ч × 7\xa0₽ + ночь 20 кВт·ч × 3\xa0₽')

    def test_starting_reading_is_the_first_previous(self):
        receipt = self.add('water', tariff=Decimal('300'))
        meter = receipt.meters.get(tenant=self.viktor)
        meter.initial = Decimal('42')
        meter.save()
        reading = dict((m.pk, r) for m, r in services.month_bill(self.prop, SEPT).entries[0].readings)[meter.pk]
        self.assertEqual(reading.previous, Decimal('42'))

    def test_common_plus_own_meters_difference_stays_with_owner(self):
        receipt = self.add('water', layout=Receipt.Layout.BOTH, tariff=Decimal('100'))
        common = receipt.meters.get(tenant=None)
        viktor_meter = receipt.meters.get(tenant=self.viktor)
        vlad_meter = receipt.meters.get(tenant=self.vlad)
        services.save_month_input(self.prop, SEPT, {
            f'prev-{common.pk}': '0', f'cur-{common.pk}': '10',
            f'prev-{viktor_meter.pk}': '0', f'cur-{viktor_meter.pk}': '4',
            f'prev-{vlad_meter.pk}': '0', f'cur-{vlad_meter.pk}': '5',
        })
        bill = services.month_bill(self.prop, SEPT)
        self.assertEqual(bill.entries[0].total, Decimal('1000.00'))
        self.assertEqual(bill.to_invoice, Decimal('900.00'))
        self.assertEqual(bill.owner.total, Decimal('100.00'))

    def test_months_are_separate(self):
        receipt = self.add('management')
        services.save_month_input(self.prop, SEPT, {f'amount-{receipt.pk}': '1000'})
        self.assertEqual(services.month_bill(self.prop, AUG).missing, [receipt])

    def test_coefficient_raises_tenant_bills_only(self):
        receipt = self.add('management', name='Содержание и ремонт')
        services.save_month_input(self.prop, SEPT, {f'amount-{receipt.pk}': '4200', f'coef-{receipt.pk}': '1,2'})
        receipt.refresh_from_db()
        self.assertEqual(receipt.coefficient, Decimal('1.2'))

        bill = services.month_bill(self.prop, SEPT)
        line = self.line(bill, self.viktor, receipt)
        self.assertEqual(line.amount, Decimal('2268.00'))   # 4 200 × 45 % × 1,2
        self.assertEqual(line.formula, '4 200,00 ₽ × 45% × 1,2')
        self.assertEqual(bill.to_invoice, Decimal('5040.00'))
        self.assertEqual(bill.owner.total, 0, 'the markup is not an owner expense')

    def test_coefficient_on_meters_and_with_free_share(self):
        self.vlad.share_percent = Decimal('30')
        self.vlad.save()
        light = self.add('electricity', tariff=Decimal('5'), coefficient=Decimal('1.1'))
        meter = light.meters.get(tenant=self.viktor)
        other = light.meters.get(tenant=self.vlad)
        services.save_month_input(self.prop, SEPT, {
            f'prev-{meter.pk}': '0', f'cur-{meter.pk}': '100', f'prev-{other.pk}': '0', f'cur-{other.pk}': '0',
        })
        water = self.add('management')
        services.save_month_input(self.prop, SEPT, {f'amount-{water.pk}': '1000', f'coef-{water.pk}': '2'})

        bill = services.month_bill(self.prop, SEPT)
        self.assertEqual(self.line(bill, self.viktor, light).amount, Decimal('550.00'))
        self.assertEqual(bill.entries[0].total, Decimal('500.00'))
        # 25 % of the 1 000 is unoccupied: the owner keeps 250, without the coefficient.
        self.assertEqual(bill.owner.total, Decimal('250.00'))

    def test_bad_coefficient_falls_back_to_one(self):
        receipt = self.add('management')
        for bad in ('', '0', '-1', 'abc', '1000'):
            services.save_month_input(self.prop, SEPT, {f'coef-{receipt.pk}': bad})
            receipt.refresh_from_db()
            self.assertEqual(receipt.coefficient, 1, bad)

    def test_parse_and_format(self):
        self.assertEqual(services.parse_decimal('4 200,50'), Decimal('4200.50'))
        self.assertIsNone(services.parse_decimal('abc'))
        self.assertIsNone(services.parse_decimal(''))
        self.assertEqual(services.fmt_number(Decimal('14961.49'), 2), '14 961,49')
        self.assertEqual(services.fmt_number(Decimal('6.50')), '6,5')


class ObjectMetersTariffTests(TestCase):
    """«Счётчик: Да» from the window: the object's meters ticked, a tariff per kind of them."""

    def setUp(self):
        user = User.objects.create_user(username='b@example.ru', email='b@example.ru', password='secret1')
        self.prop = Property.objects.create(owner=user, name='Королева 61', area=Decimal('60'))
        self.viktor = Tenant.objects.create(property=self.prop, name='Виктор', share_percent=Decimal('45'))
        self.vlad = Tenant.objects.create(property=self.prop, name='Владислав', share_percent=Decimal('55'))

    def meter(self, kind, name, unit, tenant=None, **extra):
        return Meter.objects.create(property=self.prop, kind=kind, name=name, unit=unit, tenant=tenant, **extra)

    def save(self, kind, meters, tariffs, today=datetime.date(2026, 9, 10), **changes):
        receipt = services.new_receipt(self.prop, kind)
        receipt.metered = True
        for name, value in changes.items():
            setattr(receipt, name, value)
        return services.save_receipt(receipt, meter_ids=[m.pk for m in meters], tariffs=tariffs, today=today)

    def readings(self, month, **values):
        services.save_month_input(self.prop, month, values)

    def line(self, bill, tenant, receipt):
        return next(line for line in bill.payer_for(tenant.pk).lines if line.receipt.pk == receipt.pk)

    def test_each_kind_counts_by_its_own_tariff(self):
        cold = self.meter('water', 'Вода холодная', 'м³', self.viktor)
        hot = self.meter('hot_water', 'Вода горячая', 'м³', self.vlad)
        receipt = self.save('water', [cold, hot], {'water': (Decimal('45.5'), None), 'hot_water': (Decimal('230'), None)})
        self.assertEqual(receipt.split, Receipt.Split.METERS)
        self.readings(SEPT, **{f'prev-{cold.pk}': '0', f'cur-{cold.pk}': '2', f'prev-{hot.pk}': '0', f'cur-{hot.pk}': '2'})
        bill = services.month_bill(self.prop, SEPT)
        self.assertEqual(self.line(bill, self.viktor, receipt).amount, Decimal('91.00'))
        self.assertEqual(self.line(bill, self.vlad, receipt).amount, Decimal('460.00'))
        self.assertEqual(bill.entries[0].tariff_lines, ['Вода холодная 45,5\xa0₽ за м³', 'Вода горячая 230\xa0₽ за м³'])

    def test_new_tariff_from_this_month_past_months_keep_the_old(self):
        light = self.meter('electricity', 'Электричество', 'кВт·ч')
        receipt = self.save('electricity', [light], {'electricity': (Decimal('5'), None)})
        self.readings(AUG, **{f'prev-{light.pk}': '0', f'cur-{light.pk}': '10'})
        self.readings(SEPT, **{f'cur-{light.pk}': '20'})

        receipt.refresh_from_db()
        services.save_receipt(receipt, meter_ids=[light.pk], tariffs={'electricity': (Decimal('7'), None)},
                              today=datetime.date(2026, 9, 15))

        self.assertEqual(services.month_bill(self.prop, AUG).entries[0].total, Decimal('50.00'))
        self.assertEqual(services.month_bill(self.prop, SEPT).entries[0].total, Decimal('70.00'))
        # Changed again the same month: the month's row is corrected, not doubled.
        services.save_receipt(receipt, meter_ids=[light.pk], tariffs={'electricity': (Decimal('8'), None)},
                              today=datetime.date(2026, 9, 20))
        self.assertEqual(receipt.tariffs.count(), 2)
        self.assertEqual(services.month_bill(self.prop, SEPT).entries[0].total, Decimal('80.00'))

    def test_day_night_follows_the_meter(self):
        light = self.meter('electricity', 'Электричество', 'кВт·ч', self.viktor, day_night=True)
        receipt = self.save('electricity', [light], {'electricity': (Decimal('7'), Decimal('3'))})
        self.assertEqual(receipt.zones, 2)
        self.readings(SEPT, **{f'prev-{light.pk}': '0', f'cur-{light.pk}': '10',
                               f'prevn-{light.pk}': '0', f'curn-{light.pk}': '20'})
        bill = services.month_bill(self.prop, SEPT)
        self.assertEqual(self.line(bill, self.viktor, receipt).amount, Decimal('130.00'))
        self.assertEqual(bill.entries[0].tariff_lines, ['день 7 · ночь 3\xa0₽ за кВт·ч'])

    def test_sewage_one_tariff_on_cold_and_hot_water(self):
        cold = self.meter('water', 'Вода холодная', 'м³', self.viktor)
        hot = self.meter('hot_water', 'Вода горячая', 'м³', self.viktor)
        receipt = self.save('sewage', [cold, hot], {'*': (Decimal('35'), None)})
        self.readings(SEPT, **{f'prev-{cold.pk}': '0', f'cur-{cold.pk}': '4', f'prev-{hot.pk}': '0', f'cur-{hot.pk}': '1'})
        payer = services.month_bill(self.prop, SEPT).payer_for(self.viktor.pk)
        self.assertEqual([line.amount for line in payer.lines], [Decimal('140.00'), Decimal('35.00')])

    def test_common_meter_is_split_and_unticking_keeps_the_meter(self):
        common = self.meter('electricity', 'Электричество', 'кВт·ч')
        other = self.meter('water', 'Вода холодная', 'м³')
        receipt = self.save('electricity', [common], {'electricity': (Decimal('10'), None)})
        self.assertEqual(receipt.layout, Receipt.Layout.COMMON)
        self.assertEqual(receipt.split, Receipt.Split.SHARES)
        receipt.metered = False
        services.save_receipt(receipt, meter_ids=[], tariffs={})
        self.assertFalse(receipt.meters.exists())
        self.assertEqual(self.prop.meters.count(), 2, 'the object keeps its meters')
        self.assertTrue(Meter.objects.filter(pk=other.pk).exists())

    def test_template_ticks_its_kind_and_missing_tariffs(self):
        light = self.meter('electricity', 'Электричество', 'кВт·ч', day_night=True)
        cold = self.meter('water', 'Вода холодная', 'м³')
        hot = self.meter('hot_water', 'Вода горячая', 'м³')
        self.assertEqual(services.default_meter_ids(services.new_receipt(self.prop, 'electricity')), [light.pk])
        self.assertEqual(services.default_meter_ids(services.new_receipt(self.prop, 'sewage')), [cold.pk, hot.pk])
        receipt = services.new_receipt(self.prop, 'electricity')
        # A tariff per meter (2026-11-13); one typed for its kind (older forms) still counts.
        key = f'm:{light.pk}'
        self.assertEqual(services.missing_tariffs(receipt, [light], {key: (Decimal('7'), None)}), [key])
        self.assertEqual(services.missing_tariffs(receipt, [light], {key: (Decimal('7'), Decimal('3'))}), [])
        self.assertEqual(services.missing_tariffs(receipt, [light], {'electricity': (Decimal('7'), Decimal('3'))}), [])
