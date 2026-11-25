from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.properties.models import Property
from apps.properties.services import free_meters, setup_steps
from apps.tenants.models import Tenant

from . import services
from .models import Meter, MeterTariff, MonthlyAmount, PayBundle, Payment, Reading, Receipt

User = get_user_model()


def make_property(owner, **extra):
    return Property.objects.create(owner=owner, name='Королева 61', kind='commercial', **extra)


class ReceiptServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='a@example.ru', email='a@example.ru', password='secret1')
        self.prop = make_property(self.user)
        self.viktor = Tenant.objects.create(property=self.prop, name='Виктор', share_percent=Decimal('45'))
        self.vlad = Tenant.objects.create(property=self.prop, name='Владислав', share_percent=Decimal('55'))

    def test_presets(self):
        light = services.new_receipt(self.prop, 'electricity')
        self.assertEqual(light.name, 'Электричество')
        self.assertTrue(light.metered)
        self.assertEqual(light.unit, 'кВт·ч')
        self.assertEqual(light.split, Receipt.Split.METERS)

        repair = services.new_receipt(self.prop, 'capital_repair')
        self.assertEqual(repair.split, Receipt.Split.OWNER)

        internet = services.new_receipt(self.prop, 'internet')
        self.assertEqual(internet.amount_mode, Receipt.AmountMode.FIXED)

        unknown = services.new_receipt(self.prop, 'nonsense')
        self.assertEqual(unknown.kind, Receipt.Kind.CUSTOM)
        self.assertEqual(unknown.name, '')

    def test_currency_is_explicit(self):
        receipt = services.save_receipt(services.new_receipt(self.prop, 'management'))
        self.assertEqual(receipt.currency, 'RUB')
        self.assertEqual(receipt.currency_symbol, '₽')

    def test_split_by_readings_gives_each_tenant_a_meter(self):
        receipt = services.save_receipt(services.new_receipt(self.prop, 'electricity'))
        self.assertEqual(
            sorted(receipt.meters.values_list('tenant__name', flat=True)),
            ['Виктор', 'Владислав'],
        )

    def test_common_meter_layout_has_one_common_meter(self):
        receipt = services.new_receipt(self.prop, 'water')
        receipt.layout = Receipt.Layout.COMMON
        services.save_receipt(receipt)
        meters = list(receipt.meters.all())
        self.assertEqual(len(meters), 1)
        self.assertIsNone(meters[0].tenant)
        self.assertEqual(receipt.split, Receipt.Split.SHARES, 'a common meter is split like a sum')

    def test_common_plus_own_meters(self):
        receipt = services.new_receipt(self.prop, 'water')
        receipt.layout = Receipt.Layout.BOTH
        services.save_receipt(receipt)
        meters = receipt.meters.all()
        self.assertEqual(sorted(meter.who for meter in meters), ['Виктор', 'Владислав', 'Объект (общий)'])
        self.assertEqual({meter.name for meter in meters}, {'Вода холодная'}, 'the name says what it measures')
        self.assertEqual(receipt.split, Receipt.Split.METERS)

    def test_single_rate_drops_the_night_tariff(self):
        receipt = services.new_receipt(self.prop, 'electricity')
        receipt.tariff, receipt.tariff_night = Decimal('7'), Decimal('3')
        services.save_receipt(receipt)
        self.assertIsNone(receipt.tariff_night)

    def meter(self, **values):
        return {'id': None, 'kind': 'water', 'name': 'Вода холодная', 'tenant_id': None, 'serial': '',
                'tariff': None, 'tariff_night': None, 'unit': 'м³', 'initial': None, 'initial_night': None,
                **values}

    def test_meter_list_from_the_window(self):
        receipt = services.new_receipt(self.prop, 'water')
        services.save_receipt(receipt, meters=[
            self.meter(tenant_id=self.viktor.pk, serial='0123', initial=Decimal('1000')),
            self.meter(kind='hot_water', name='Вода горячая', tenant_id=self.viktor.pk, tariff=Decimal('230')),
        ])
        self.assertEqual(receipt.layout, Receipt.Layout.TENANTS, 'only tenants\' meters')
        cold, hot = receipt.meters.order_by('id')
        self.assertEqual((cold.serial, cold.initial, cold.tenant), ('0123', Decimal('1000'), self.viktor))
        self.assertEqual((hot.name, hot.tariff), ('Вода горячая', Decimal('230')))

        # Edited: the known one kept, the removed one gone, a common one added → both layouts.
        services.save_receipt(receipt, meters=[
            self.meter(id=cold.pk, tenant_id=self.viktor.pk, serial='0123'),
            self.meter(kind='custom', name='Полив'),
        ])
        self.assertEqual(receipt.layout, Receipt.Layout.BOTH)
        self.assertEqual(sorted(receipt.meters.values_list('name', flat=True)), ['Вода холодная', 'Полив'])
        self.assertTrue(Meter.objects.filter(pk=cold.pk).exists())
        self.assertFalse(Meter.objects.filter(pk=hot.pk).exists())
        self.assertIn({'kind': 'custom', 'name': 'Полив', 'unit': 'м³'}, services.meter_kind_options(self.prop))
        # The menu: electricity, water and gas, and «Счётчик» (nobody's name) is not an own variant.
        self.meter(kind='custom', name='')
        services.save_meter(self.prop, {'kind': 'custom', 'name': ''})
        names = [option['name'] for option in services.meter_kind_options(self.prop)]
        self.assertEqual(names, ['Электричество', 'Вода холодная', 'Вода горячая', 'Газ', 'Полив'])

    def test_meter_saved_from_its_row_then_linked_by_the_service(self):
        row = {'id': '', 'kind': 'water', 'name': 'Вода холодная', 'who': str(self.viktor.pk), 'serial': '0123',
               'tariff': '45,50', 'tariffn': '', 'unit': 'м³', 'initial': '120', 'initialn': ''}
        meter = services.save_meter(self.prop, row)
        self.assertEqual((meter.property, meter.tenant, meter.tariff), (self.prop, self.viktor, Decimal('45.50')))

        services.save_meter(self.prop, {**row, 'id': str(meter.pk), 'serial': '0124'})
        meter.refresh_from_db()
        self.assertEqual(meter.serial, '0124')

        receipt = services.save_receipt(services.new_receipt(self.prop, 'water'), meters=[
            services.clean_meter(self.prop, {**row, 'id': str(meter.pk)}),
        ])
        self.assertEqual(list(receipt.meters.all()), [meter], 'the saved meter is linked, not copied')
        self.assertEqual(self.prop.meters.count(), 1)

    def test_delete_meter_keeps_one_another_service_uses(self):
        water = services.save_receipt(services.new_receipt(self.prop, 'water'))
        sewage = services.save_receipt(services.new_receipt(self.prop, 'sewage'))
        shared = water.meters.get(tenant=self.viktor)
        sewage.meters.add(shared)
        self.assertFalse(services.delete_meter(shared, keep_for=water.pk))
        own = water.meters.get(tenant=self.vlad)
        self.assertTrue(services.delete_meter(own, keep_for=water.pk))
        self.assertFalse(Meter.objects.filter(pk=own.pk).exists())

    def test_unmetered_receipt_drops_meters_and_reading_split(self):
        receipt = services.save_receipt(services.new_receipt(self.prop, 'electricity'))
        receipt.metered = False
        services.save_receipt(receipt)
        self.assertEqual(receipt.split, Receipt.Split.SHARES)
        self.assertEqual(receipt.unit, '')
        self.assertFalse(receipt.meters.exists())

    def test_metered_receipt_is_never_fixed(self):
        receipt = services.new_receipt(self.prop, 'electricity')
        receipt.amount_mode = Receipt.AmountMode.FIXED
        receipt.fixed_amount = Decimal('100')
        services.save_receipt(receipt)
        self.assertEqual(receipt.amount_mode, Receipt.AmountMode.MONTHLY)
        self.assertIsNone(receipt.fixed_amount)

    def test_a_tenant_moving_out_leaves_the_meter_free(self):
        receipt = services.save_receipt(services.new_receipt(self.prop, 'electricity'))
        vlad_meter = receipt.meters.get(tenant=self.vlad)

        free_meters(self.vlad)
        self.vlad.delete()
        Tenant.objects.create(property=self.prop, name='Ольга', share_percent=Decimal('55'))
        services.resync_property(self.prop)

        vlad_meter.refresh_from_db()
        self.assertTrue(vlad_meter.vacant, 'the meter stays on the object, free')
        self.assertIsNone(vlad_meter.tenant)
        self.assertEqual(receipt.meters.count(), 2, 'no meter is added or removed behind the owner')
        receipt.refresh_from_db()
        self.assertEqual(receipt.layout, Receipt.Layout.TENANTS, 'a free meter is not a common one')

    def test_meters_belong_to_the_object(self):
        receipt = services.save_receipt(services.new_receipt(self.prop, 'electricity'))
        self.assertEqual(self.prop.meters.count(), 2)
        meter = self.prop.meters.get(tenant=self.viktor)
        self.assertEqual(meter.kind, 'electricity')
        self.assertEqual(list(meter.receipts.all()), [receipt])

    def test_a_meter_can_serve_two_services(self):
        water = services.save_receipt(services.new_receipt(self.prop, 'water'))
        sewage = services.save_receipt(services.new_receipt(self.prop, 'sewage'))
        shared = water.meters.get(tenant=self.viktor)
        unused = water.meters.get(tenant=self.vlad)
        sewage.meters.add(shared)

        services.delete_receipt(water)
        self.assertTrue(Meter.objects.filter(pk=shared.pk).exists(), 'still used by sewage')
        # The meters are the premises': deleting a service leaves them on the object.
        self.assertTrue(Meter.objects.filter(pk=unused.pk).exists(), 'stays on the object')

    def test_unlinked_meter_goes_away_when_layout_changes(self):
        receipt = services.save_receipt(services.new_receipt(self.prop, 'electricity'))
        receipt.layout = Receipt.Layout.COMMON
        services.save_receipt(receipt)
        self.assertEqual(list(self.prop.meters.values_list('tenant', flat=True)), [None])

    def test_owner_used_object(self):
        self.prop.occupancy = Property.Occupancy.OWNER
        self.prop.save()
        management = services.save_receipt(services.new_receipt(self.prop, 'management'))
        self.assertEqual(management.split, Receipt.Split.OWNER)
        light = services.save_receipt(services.new_receipt(self.prop, 'electricity'))
        self.assertEqual([m.tenant for m in light.meters.all()], [None])

    def test_missing_kinds(self):
        services.save_receipt(services.new_receipt(self.prop, 'electricity'))
        kinds = services.missing_kinds(self.prop)
        self.assertNotIn(Receipt.Kind.ELECTRICITY, kinds)
        self.assertIn(Receipt.Kind.WATER, kinds)
        self.assertNotIn(Receipt.Kind.CUSTOM, kinds)

    def test_area_split_warning(self):
        receipt = services.new_receipt(self.prop, 'management')
        receipt.split = Receipt.Split.AREA
        self.assertIn('м²', services.split_warning(receipt))

    def test_setup_step_done_after_first_receipt(self):
        self.assertEqual(setup_steps(self.prop)['done'], 2)
        services.save_receipt(services.new_receipt(self.prop, 'management'))
        setup = setup_steps(self.prop)
        self.assertTrue(setup['complete'])


class ReceiptViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='a@example.ru', email='a@example.ru', password='secret1')
        self.other = User.objects.create_user(username='b@example.ru', email='b@example.ru', password='secret1')
        self.prop = make_property(self.user)
        Tenant.objects.create(property=self.prop, name='Виктор', share_percent=Decimal('100'))
        self.client.force_login(self.user)

    def test_object_page_offers_receipt_buttons(self):
        response = self.client.get(reverse('property_detail', args=[self.prop.pk]))
        self.assertContains(response, 'Какие услуги оплачиваете по объекту?')
        self.assertContains(response, reverse('service_window', args=[self.prop.pk]))

    def test_meter_row_save_and_delete(self):
        url = reverse('meter_save', args=[self.prop.pk])
        response = self.client.post(url, {'meter_kind': 'custom', 'meter_name': 'Полив', 'meter_tariff': '30'})
        meter = self.prop.meters.get(pk=response.json()['id'])
        self.assertEqual((meter.name, meter.tariff, meter.tenant), ('Полив', Decimal('30'), None))

        self.client.force_login(self.other)
        self.assertEqual(self.client.post(url, {'meter_kind': 'gas'}).status_code, 404)
        self.assertEqual(self.client.post(reverse('meter_delete', args=[meter.pk])).status_code, 404)

        self.client.force_login(self.user)
        response = self.client.post(reverse('meter_delete', args=[meter.pk]))
        self.assertTrue(response.json()['deleted'])
        self.assertFalse(self.prop.meters.exists())

    def _light_service(self, *meters, name=None, tariffs=None):
        """A service «По счётчикам» by the given meters; each meter's tariff (day, night) — 5,50 ₽ unless given."""
        for meter in meters:
            day, night = (tariffs or {}).get(meter, (Decimal('5.50'), None))
            services.save_meter_tariff(meter, day, night)
        receipt = services.new_receipt(self.prop, 'electricity')
        receipt.name = name or receipt.name
        receipt.metered = True
        return services.save_receipt(receipt, meter_ids=[m.pk for m in meters], tariffs={})

    def test_tariffs_page(self):
        # 2026-11-17: «Услуги → Тарифы» — every tariff in force; a row opens where it is changed (2026-11-23):
        # a meter's — the object window on that meter, the rest — the service. Nothing is added or deleted here.
        light = Meter.objects.create(property=self.prop, kind='electricity', name='Электричество', unit='кВт·ч', serial='222')
        self._light_service(light)
        receipt = self.prop.receipts.get()
        area = Receipt.objects.create(property=self.prop, kind='custom', name='Содержание', amount_mode='rate',
                                      rate_base='area', rate=Decimal('7.12'))
        stranger = Receipt.objects.create(property=make_property(self.other), kind='custom', name='Чужая',
                                          amount_mode='rate', rate_base='area', rate=Decimal('99'))

        response = self.client.get(reverse('tariff_list'))
        self.assertContains(response, 'Электричество № 222')
        self.assertContains(response, '5,5 ₽/кВт·ч')
        self.assertContains(response, '7,12\xa0₽/м²')
        self.assertContains(response, 'с начала')
        window = reverse('service_window', args=[self.prop.pk])
        edit = reverse('property_edit', args=[self.prop.pk])
        self.assertContains(response, f'data-row-modal="{edit}?meter={light.pk}"')
        self.assertNotContains(response, f'data-row-modal="{window}?svc={receipt.pk}"')
        self.assertContains(response, f'data-row-modal="{window}?svc={area.pk}"')
        self.assertNotContains(response, stranger.name)
        self.assertNotContains(response, reverse('receipt_delete', args=[area.pk]))
        self.assertNotContains(response, 'btn btn-primary')  # no «Добавить услугу» on the page (the menu's «+» stays)

        # The object window opened from such a row: on the meters, that meter's small window; a stranger's id — ignored.
        response = self.client.get(f'{edit}?meter={light.pk}', HTTP_X_MODAL='1')
        self.assertContains(response, f'data-open-meter="{light.pk}"')
        self.assertEqual(response.context['open_part'], 'meters')
        other_meter = Meter.objects.create(property=make_property(self.other), kind='gas', name='Газ', unit='м³')
        response = self.client.get(f'{edit}?meter={other_meter.pk}', HTTP_X_MODAL='1')
        self.assertNotContains(response, 'data-open-meter')
        self.assertEqual(response.context['open_part'], 'object')

        # A new price starts this month; the page says since when and what it was before.
        MeterTariff.objects.filter(meter=light).update(valid_from=date(2026, 1, 1))
        MeterTariff.objects.create(meter=light, valid_from=date(2026, 11, 1), tariff=Decimal('6'))
        rows = services.tariff_table(self.user, today=date(2026, 11, 17))[0]['rows']
        row = next(row for row in rows if row['receipt'] == receipt)
        self.assertEqual((row['price'], row['since'], row['before']), ('6 ₽/кВт·ч', 'с ноября 2026', '5,5 ₽/кВт·ч'))
        earlier = services.tariff_table(self.user, today=date(2026, 10, 5))[0]['rows']
        self.assertEqual(next(r for r in earlier if r['receipt'] == receipt)['since'], 'с января 2026')

        # «История» (2026-11-25): every price old to new, the one in force «сейчас» — a meter's too, only the prices.
        self.assertEqual(row['history'], [{'from': 'с января 2026', 'price': '5,5 ₽/кВт·ч', 'now': False},
                                          {'from': 'с ноября 2026', 'price': '6 ₽/кВт·ч', 'now': True}])
        self.assertNotContains(self.client.get(reverse('tariff_list')), reverse('meter_history', args=[light.pk]))
        meter_window = self.client.get(reverse('tariff_history', args=[receipt.pk]) + '?key=' + row['key'], HTTP_X_MODAL='1')
        self.assertContains(meter_window, 'окне счётчика')
        self.assertNotContains(meter_window, 'Показания')
        area_row = next(r for r in rows if r['receipt'] == area)
        url = reverse('tariff_history', args=[area.pk]) + '?key=' + area_row['key']
        window = self.client.get(url, HTTP_X_MODAL='1')
        self.assertContains(window, area_row['history'][-1]['price'])
        self.assertContains(window, 'сейчас')
        self.assertEqual(self.client.get(reverse('tariff_history', args=[area.pk]) + '?key=nope').status_code, 404)

    def test_all_meters_page(self):
        tenant = self.prop.tenants.get()
        light = Meter.objects.create(property=self.prop, kind='electricity', name='Электричество', unit='кВт·ч',
                                     serial='222', tenant=tenant, initial=Decimal('100'))
        water = Meter.objects.create(property=self.prop, kind='water', name='Вода холодная', unit='м³', serial='444')
        self._light_service(light)
        receipt = self.prop.receipts.get()
        Reading.objects.create(meter=light, month=date(2026, 11, 1), current=Decimal('339'))
        Meter.objects.create(property=make_property(self.other), kind='gas', name='Чужой газ')

        response = self.client.get(reverse('meter_list'))
        self.assertContains(response, '№ 222')
        self.assertContains(response, tenant.name)
        self.assertContains(response, '5,5 ₽/кВт·ч')  # the meter's tariff
        self.assertContains(response, '339 кВт·ч')
        self.assertContains(response, 'ноябрь 2026')
        self.assertContains(response, 'не в услуге')  # the water meter
        self.assertContains(response, f'data-row-modal="{reverse("service_window", args=[self.prop.pk])}?svc={receipt.pk}"')
        # Not in a service: the service window, a new service «По счётчикам» with this meter switched on.
        new_url = reverse('service_window', args=[self.prop.pk]) + f'?meter={water.pk}'
        self.assertContains(response, f'data-row-modal="{new_url}"')
        self.assertContains(response, reverse('meter_remove', args=[water.pk]))
        self.assertNotContains(response, 'Чужой газ')
        self.assertEqual(response.context['sidebar_meter_count'](), 2)

    def test_objects_page_shows_the_months_numbers(self):
        light = Meter.objects.create(property=self.prop, kind='electricity', name='Электричество', unit='кВт·ч',
                                     initial=Decimal('100'))
        self._light_service(light)
        Reading.objects.create(meter=light, month=date(2026, 11, 1), current=Decimal('110'))  # 10 × 5,50 = 55
        response = self.client.get(reverse('property_list') + '?month=2026-11')
        prop = response.context['properties'][0]
        self.assertEqual((prop.bill.readings_done, prop.bill.readings_total), (1, 1))
        self.assertEqual(prop.bill.to_invoice, Decimal('55.00'))
        summary = response.context['summary']
        self.assertEqual((summary['to_invoice'], summary['readings_done'], summary['readings_total']),
                         (Decimal('55.00'), 1, 1))
        self.assertEqual((summary['tenants'], summary['tenants_ready']), (1, 1))
        self.assertContains(response, '1 из 1')
        self.assertNotContains(response, '0,00&nbsp;₽</span><span class="stat-cap">начисления')  # no placeholder

    def test_remove_meter_from_the_list(self):
        light = Meter.objects.create(property=self.prop, kind='electricity', name='Электричество', unit='кВт·ч')
        water = Meter.objects.create(property=self.prop, kind='water', name='Вода холодная', unit='м³')
        self._light_service(light)
        url = reverse('meter_remove', args=[light.pk])
        self.assertContains(self.client.get(url, HTTP_X_MODAL='1'), 'Счётчик привязан к услуге')
        self.client.post(url, HTTP_X_MODAL='1')
        self.assertTrue(Meter.objects.filter(pk=light.pk).exists(), 'a meter in a service is not deleted')

        url = reverse('meter_remove', args=[water.pk])
        self.assertContains(self.client.get(url, HTTP_X_MODAL='1'), 'Удалить счётчик')
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(url).status_code, 404)
        self.client.force_login(self.user)
        response = self.client.post(url, HTTP_X_MODAL='1')
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Meter.objects.filter(pk=water.pk).exists())

    def test_add_meter_from_the_menu_opens_the_object_window(self):
        response = self.client.get(reverse('meter_add'), HTTP_X_MODAL='1')
        self.assertContains(response, 'data-property-form')  # one object: straight into its window
        Property.objects.create(owner=self.user, name='Второй', kind='commercial')
        response = self.client.get(reverse('meter_add'), HTTP_X_MODAL='1')
        self.assertContains(response, 'К какому объекту?')
        self.assertContains(response, reverse('property_edit', args=[self.prop.pk]))

    def test_object_window_marks_meters_a_service_counts_by(self):
        light = Meter.objects.create(property=self.prop, kind='electricity', name='Электричество', unit='кВт·ч')
        Meter.objects.create(property=self.prop, kind='water', name='Вода холодная', unit='м³')
        self._light_service(light)
        receipt = self.prop.receipts.get()
        response = self.client.get(reverse('property_edit', args=[self.prop.pk]), HTTP_X_MODAL='1')
        # × on this meter shows «Счётчик привязан к услуге» instead of deleting it (app.js); the free one has no mark.
        self.assertContains(response, 'data-services="«Электричество»"', count=1)
        self.assertContains(response, f'data-service-url="{reverse("service_window", args=[self.prop.pk])}?svc={receipt.pk}"')

    def test_usage_mode_is_saved_and_the_object_page_asks_for_usage(self):
        meter = Meter.objects.create(property=self.prop, kind='electricity', name='Электричество', unit='кВт·ч',
                                     input_mode='usage')
        self._light_service(meter, name='Свет')
        page = self.client.get(reverse('property_detail', args=[self.prop.pk]))
        self.assertContains(page, f'name="use-{meter.pk}"')
        self.assertNotContains(page, f'name="cur-{meter.pk}"')
        self.assertContains(page, 'mread-meta')
        self.assertNotContains(page, 'mreceipt-tariff')  # the tariff is next to the meter's № now (2026-11-15)

    def test_only_a_day_night_meter_has_a_night_row(self):
        one = Meter.objects.create(property=self.prop, kind='electricity', name='Электричество', unit='кВт·ч')
        two = Meter.objects.create(property=self.prop, kind='electricity', name='Электричество', unit='кВт·ч',
                                   day_night=True)
        self._light_service(one, two, name='Свет', tariffs={one: (Decimal('5'), None), two: (Decimal('6'), Decimal('3'))})
        page = self.client.get(reverse('property_detail', args=[self.prop.pk]))
        self.assertContains(page, f'name="curn-{two.pk}"')
        self.assertNotContains(page, f'name="curn-{one.pk}"')
        self.assertContains(page, '· 5 ₽/кВт·ч')  # a single-rate meter: one price
        self.assertContains(page, '· 6 / 3 ₽/кВт·ч')

    def test_usage_row_shows_last_months_usage_until_this_ones_is_typed(self):
        meter = Meter.objects.create(property=self.prop, kind='electricity', name='Электричество', unit='кВт·ч',
                                     input_mode='usage')
        self._light_service(meter, name='Свет')
        Reading.objects.create(meter=meter, month=date(2026, 10, 1), usage=Decimal('42'))
        url = reverse('property_detail', args=[self.prop.pk]) + '?month=2026-11'
        self.assertContains(self.client.get(url), 'class="badge mread-last">42 кВт·ч</span>')
        Reading.objects.create(meter=meter, month=date(2026, 11, 1), usage=Decimal('50'))
        page = self.client.get(url)
        self.assertNotContains(page, 'mread-last')
        self.assertContains(page, '>50 кВт·ч<')

    def test_each_meter_has_its_own_input_mode(self):
        """«Было / стало | Расход» at each meter (2026-11-16): one service, one meter by readings, one by usage."""
        one = Meter.objects.create(property=self.prop, kind='electricity', name='Электричество', unit='кВт·ч',
                                   initial=Decimal('100'), input_mode='readings')
        two = Meter.objects.create(property=self.prop, kind='electricity', name='Электричество', unit='кВт·ч',
                                   input_mode='usage')
        self._light_service(one, two, name='Свет')
        Reading.objects.create(meter=one, month=date(2026, 11, 1), previous=Decimal('100'), current=Decimal('110'))
        Reading.objects.create(meter=two, month=date(2026, 11, 1), usage=Decimal('7'))
        page = self.client.get(reverse('property_detail', args=[self.prop.pk]) + '?month=2026-11')
        self.assertContains(page, f'name="cur-{one.pk}"')
        self.assertContains(page, f'name="use-{two.pk}"')
        self.assertContains(page, 'class="mread-in is-add" data-zone="+"')  # a «Расход» meter: the field adds to the meter (2026-11-23)
        receipt = Receipt.objects.get(name='Свет')
        self.assertEqual(services.used(receipt, Reading.objects.get(meter=one)), (Decimal('10'), None))
        self.assertEqual(services.used(receipt, Reading.objects.get(meter=two))[0], Decimal('7'))

    def test_delete(self):
        receipt = services.save_receipt(services.new_receipt(self.prop, 'management'))
        self.client.post(reverse('receipt_delete', args=[receipt.pk]))
        self.assertFalse(Receipt.objects.filter(pk=receipt.pk).exists())

    def test_other_landlords_receipts_are_not_reachable(self):
        foreign_prop = make_property(self.other)
        foreign = services.save_receipt(services.new_receipt(foreign_prop, 'management'))
        self.assertEqual(self.client.get(reverse('service_window', args=[foreign_prop.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('receipt_delete', args=[foreign.pk])).status_code, 404)
        self.client.post(reverse('receipt_delete', args=[foreign.pk]))
        self.assertTrue(Receipt.objects.filter(pk=foreign.pk).exists())


class MonthPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='a@example.ru', email='a@example.ru', password='secret1')
        self.prop = make_property(self.user)
        self.viktor = Tenant.objects.create(property=self.prop, name='Виктор', share_percent=Decimal('45'))
        self.vlad = Tenant.objects.create(property=self.prop, name='Владислав', share_percent=Decimal('55'))
        self.receipt = services.save_receipt(services.new_receipt(self.prop, 'management'))
        self.client.force_login(self.user)

    def test_service_cards_change_places(self):
        # 2026-11-17: the owner drags the service cards of the object page; a new service goes last.
        light = services.save_receipt(services.new_receipt(self.prop, 'internet'))
        own = Receipt.objects.create(property=self.prop, kind='custom', name='Охрана')
        self.assertEqual([r.pk for r in self.prop.receipts.all()], [self.receipt.pk, light.pk, own.pk])
        stranger = Receipt.objects.create(property=make_property(
            User.objects.create_user(username='b@example.ru', password='secret1')), kind='custom', name='Чужая')

        url = reverse('receipt_order', args=[self.prop.pk])
        response = self.client.post(url, {'order': f'{own.pk},{stranger.pk},{self.receipt.pk}'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([r.pk for r in self.prop.receipts.all()], [own.pk, self.receipt.pk, light.pk])
        stranger.refresh_from_db()
        self.assertEqual(stranger.position, 1, "another owner's service is not touched")

        page = self.client.get(reverse('property_detail', args=[self.prop.pk])).content.decode()
        self.assertIn('data-order-on', page)  # «⇅ Порядок» (variant Г): folded rows in the same order
        self.assertLess(page.index(f'data-order-row data-receipt-id="{own.pk}"'),
                        page.index(f'data-order-row data-receipt-id="{self.receipt.pk}"'))
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_bill_in_groups_with_the_sum_in_words(self):
        # 2026-11-17, variant А: «Общие · по долям 45%» and «По счётчикам» in frames, «Итого к оплате» in words.
        light = Receipt.objects.create(property=self.prop, kind='electricity', name='Электричество', metered=True,
                                       split=Receipt.Split.METERS)
        payer = services.Payer(self.viktor, [
            services.Line(self.receipt, Decimal('2340.00'), '5 200,00 ₽ × 45%'),
            services.Line(light, Decimal('6575.80'), 'день …'),
        ])
        groups = services.bill_groups(payer)
        self.assertEqual([(g['title'], g['total']) for g in groups],
                         [('Общие · по долям 45%', Decimal('2340.00')), ('По счётчикам', Decimal('6575.80'))])
        self.assertEqual(services.bill_groups(services.Payer(None, payer.lines[:1]))[0]['title'], 'Общие',
                         'the owner has no share of his own')
        self.assertEqual(services.money_words(Decimal('11705.80')), 'Одиннадцать тысяч семьсот пять рублей 80 копеек')
        self.assertEqual(services.money_words(Decimal('2001.01')), 'Две тысячи один рубль 01 копейка')
        self.assertEqual(services.money_words(Decimal('0.50')), 'Ноль рублей 50 копеек')

        url = reverse('property_detail', args=[self.prop.pk]) + '?month=2026-11'
        self.assertContains(self.client.get(url), 'Пока нечего начислять')
        MonthlyAmount.objects.create(receipt=self.receipt, month=date(2026, 11, 1), amount=Decimal('5200'))
        page = self.client.get(url)
        self.assertContains(page, 'Готов к счёту')
        self.assertContains(page, 'Общие · по долям 45%')
        self.assertContains(page, 'Две тысячи триста сорок рублей 00 копеек')

        # «Счёт PDF»: a real PDF file, downloaded; the owner's bill under 0; someone else's — 404. «Поделиться» has
        # the bill as text for WhatsApp / Telegram.
        pdf = reverse('bill_print', args=[self.prop.pk, self.viktor.pk])
        self.assertContains(page, pdf + '?month=2026-11')
        self.assertContains(page, 'Поделиться')
        self.assertContains(page, 'Итого к оплате: 2\xa0340,00 ₽')
        printed = self.client.get(pdf + '?month=2026-11')
        self.assertEqual(printed['Content-Type'], 'application/pdf')
        self.assertTrue(printed.content.startswith(b'%PDF'))
        self.assertIn('attachment;', printed['Content-Disposition'])
        self.assertIn('inline;', self.client.get(pdf + '?month=2026-11&inline=1')['Content-Disposition'])
        self.assertEqual(services.bill_file_name('Аптека "Вита"', 'Ноябрь 2026'), 'Счёт ноябрь 2026 — Аптека Вита.pdf')
        self.assertEqual(self.client.get(reverse('bill_print', args=[self.prop.pk, 0]) + '?month=2026-11').status_code, 200)
        self.assertEqual(self.client.get(reverse('bill_print', args=[self.prop.pk, 99999])).status_code, 404)
        stranger = make_property(User.objects.create_user(username='s@example.ru', password='secret1'))
        self.assertEqual(self.client.get(reverse('bill_print', args=[stranger.pk, 0])).status_code, 404)

    def test_bill_shows_the_meter_month(self):
        # A meter's line: «счётчик № 222», then one grey row «100 → 104 = 4 кВт·ч × 9,5 ₽ = 38,00 ₽».
        meter = Meter.objects.create(property=self.prop, kind='electricity', name='Электричество', unit='кВт·ч',
                                     tenant=self.viktor, serial='222', initial=Decimal('100'))
        light = Receipt.objects.create(property=self.prop, kind='electricity', name='Электричество', metered=True,
                                       split=Receipt.Split.METERS, tariff=Decimal('9.5'), unit='кВт·ч')
        light.meters.add(meter)
        Reading.objects.create(meter=meter, month=date(2026, 11, 1), current=Decimal('104'))
        payer = services.month_bill(self.prop, date(2026, 11, 1)).payer_for(self.viktor.pk)
        line = next(line for line in payer.lines if line.receipt == light)
        rows = services.bill_meter_rows(line)
        self.assertEqual(rows, ['счётчик №\xa0222', '100 → 104 = 4\xa0кВт·ч × 9,5\xa0₽ = 38,00\xa0₽'])
        light.coefficient = Decimal('1.2')
        light.save()
        payer = services.month_bill(self.prop, date(2026, 11, 1)).payer_for(self.viktor.pk)
        line = next(line for line in payer.lines if line.receipt == light)
        self.assertEqual(services.bill_meter_rows(line)[-1], '× 1,2 = 45,60\xa0₽')

    def test_payments_page(self):
        # 2026-11-17: «Оплаты» — what the owner pays the providers. Variant А: one table, objects × service names
        # (same-name services of an object add up into one cell); a typed sum stands «не оплачено» until marked.
        sept, octo, nov = date(2026, 9, 1), date(2026, 10, 1), date(2026, 11, 1)
        MonthlyAmount.objects.create(receipt=self.receipt, month=octo, amount=Decimal('4200'))
        internet = services.new_receipt(self.prop, 'internet')
        internet.fixed_amount = Decimal('650')
        internet = services.save_receipt(internet)
        twin = Receipt.objects.create(property=self.prop, kind='internet', name=internet.name, amount_mode='fixed',
                                      fixed_amount=Decimal('350'))
        other = Property.objects.create(owner=self.user, name='Яблочная 2', kind='commercial')
        Receipt.objects.create(property=other, kind='management', name=self.receipt.name)  # no sum yet

        table = services.payment_table(self.user, octo)
        mine = next(row for row in table['rows'] if row['property'] == self.prop)
        self.assertEqual([tile['name'] for tile in mine['tiles']], [self.receipt.name, internet.name])
        self.assertEqual([tile['state'] for tile in mine['tiles']], ['due', 'due'])
        self.assertEqual(mine['tiles'][1]['amount'], Decimal('1000.00'), 'one tile per name, the sums add up')
        theirs = next(row for row in table['rows'] if row['property'] == other)
        self.assertEqual([(tile['name'], tile['state']) for tile in theirs['tiles']], [(self.receipt.name, 'empty')],
                         'only its own services — no empty «—» for the others')
        self.assertEqual((table['totals']['due'], table['totals']['left'], table['totals']['unpaid'], table['totals']['empty']),
                         (Decimal('5200.00'), Decimal('5200.00'), 2, 1))

        page = self.client.get(reverse('payment_list') + '?month=2026-10')
        self.assertContains(page, 'не оплачено')
        self.assertContains(page, 'Октябрь 2026')
        self.assertContains(page, 'data-pay-toggle')

        # The check: paid today — both same-name services at once; the board comes back drawn anew.
        url = reverse('payment_edit', args=[internet.pk, '2026-10'])
        response = self.client.post(url, {'paid': '1'})
        self.assertContains(response, date.today().strftime('%d.%m.%Y'))
        self.assertEqual(twin.payments.get().paid_on, date.today())
        table = services.payment_table(self.user, octo)
        self.assertEqual((table['totals']['paid'], table['totals']['left'], table['totals']['unpaid']),
                         (Decimal('1000.00'), Decimal('4200.00'), 1))
        self.client.post(url, {'paid': '1', 'paid_on': '12.10.2026'})
        cell = next(row for row in services.payment_table(self.user, octo)['rows'] if row['property'] == self.prop)['tiles'][1]
        self.assertEqual(cell['paid_on'], date(2026, 10, 12))

        # November: October's unpaid bills are over the table, marked from there (the board stays on November).
        table = services.payment_table(self.user, nov)
        self.assertEqual([(tile['name'], tile['amount']) for tile in table['prev']], [(self.receipt.name, Decimal('4200.00'))])
        self.assertEqual(table['prev_left'], Decimal('4200.00'))
        oct_url = reverse('payment_edit', args=[self.receipt.pk, '2026-10'])
        response = self.client.post(oct_url, {'paid': '1', 'view': '2026-11'})
        self.assertContains(response, 'Ноябрь 2026'.lower())
        self.assertEqual(services.payment_table(self.user, nov)['prev'], [])

        # A note with «переносить» comes by itself into the next months — marking one of them paid keeps it going;
        # a month that takes it off stops it.
        note_url = reverse('payment_edit', args=[internet.pk, '2026-09'])
        self.client.post(note_url, {'note': 'переплата 300 ₽', 'carry': '1'})
        cell_of = lambda month: next(r for r in services.payment_table(self.user, month)['rows'] if r['property'] == self.prop)['tiles'][1]  # noqa: E731
        self.assertEqual((cell_of(sept)['note'], cell_of(sept)['carry']), ('переплата 300 ₽', True))
        # October already had its own row (marked paid before the note was written): it decides for itself.
        self.assertEqual(cell_of(octo)['note'], '')
        self.assertEqual(cell_of(nov)['note'], '', 'October has its own row without the note: the chain stops there')
        dec = date(2026, 12, 1)
        self.client.post(reverse('payment_edit', args=[internet.pk, '2026-11']), {'note': 'учесть в декабре', 'carry': '1'})
        self.assertEqual(cell_of(dec)['note'], 'учесть в декабре')
        self.client.post(reverse('payment_edit', args=[internet.pk, '2026-12']), {'paid': '1'})  # paid: the note stays
        self.assertEqual(cell_of(date(2027, 1, 1))['note'], 'учесть в декабре')
        self.client.post(reverse('payment_edit', args=[internet.pk, '2027-01']), {'note': '', 'carry': '0'})
        self.assertEqual(cell_of(date(2027, 1, 1))['note'], '')
        self.assertEqual(cell_of(date(2027, 2, 1))['note'], '', 'taken off in January — not in February')
        self.assertEqual(cell_of(dec)['note'], 'учесть в декабре', 'earlier months keep theirs')
        self.client.post(reverse('payment_edit', args=[self.receipt.pk, '2026-09']), {'note': 'без переноса', 'carry': '0'})
        self.assertEqual(next(r for r in services.payment_table(self.user, octo)['rows'] if r['property'] == self.prop)['tiles'][0]['note'], '')

        # Not paid again; someone else's service can't be marked; the mark is POST only.
        self.client.post(url, {'paid': '0'})
        self.assertEqual(cell_of(octo)['state'], 'due')
        stranger = Receipt.objects.create(property=make_property(
            User.objects.create_user(username='c@example.ru', password='secret1')), kind='custom', name='Чужая')
        self.assertEqual(self.client.post(reverse('payment_edit', args=[stranger.pk, '2026-10']), {'paid': '1'}).status_code, 404)
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_meter_history(self):
        # 2026-11-25: «Счётчики → История» — readings by month, old to new, with the price and the sum of the bill;
        # a «Расход» meter's «было / стало» are counted; «По расходу» — the price comes from the receipt.
        water = Meter.objects.create(property=self.prop, kind='hot_water', name='Вода горячая', unit='м³',
                                     tenant=self.viktor, serial='333', initial=Decimal('221'))
        hot = Receipt.objects.create(property=self.prop, kind='hot_water', name='Вода горячая', metered=True,
                                     split=Receipt.Split.METERS, unit='м³')
        hot.meters.add(water)
        MeterTariff.objects.create(meter=water, valid_from=date(2000, 1, 1), tariff=Decimal('76.4'))
        MeterTariff.objects.create(meter=water, valid_from=date(2026, 10, 1), tariff=Decimal('80.7'))
        Reading.objects.create(meter=water, month=date(2026, 9, 1), current=Decimal('226'))
        Reading.objects.create(meter=water, month=date(2026, 10, 1), current=Decimal('231'))
        h = services.meter_history(water, date(2026, 11, 20))
        self.assertEqual([row.label for row in h['rows']], ['Сентябрь 2026', 'Октябрь 2026', 'Ноябрь 2026'])
        sept, octo, nov = h['rows']
        self.assertEqual((sept.was, sept.now, sept.use, sept.price, sept.total), (221, 226, 5, Decimal('76.4'), Decimal('382.00')))
        self.assertEqual((octo.price, octo.total, octo.price_changed), (Decimal('80.7'), Decimal('403.50'), True))
        self.assertTrue(nov.missing, 'this month without readings — «не введено»')
        self.assertEqual(nov.was, 231)
        self.assertEqual((h['start'], h['start_from'], h['unit']), (221, 'с сентября 2026', 'м³'))
        self.assertEqual([(t['from'], t['tariff'], t['now']) for t in h['tariffs']],
                         [('с сентября 2026', Decimal('76.4'), False), ('с октября 2026', Decimal('80.7'), True)])

        # «Расход» meters in a «По расходу» service: was = start + every usage before, the price = receipt ÷ all usage.
        light = Meter.objects.create(property=self.prop, kind='electricity', name='Электричество', unit='кВт·ч',
                                     tenant=self.viktor, serial='1', initial=Decimal('12400'), input_mode='usage')
        other = Meter.objects.create(property=self.prop, kind='electricity', name='Электричество', unit='кВт·ч',
                                     serial='2', initial=Decimal('500'), input_mode='usage')
        split = Receipt.objects.create(property=self.prop, kind='electricity', name='Электричество',
                                       split=Receipt.Split.USAGE)
        split.meters.add(light, other)
        for month, mine, theirs, total in ((date(2026, 9, 1), 341, 59, 3600), (date(2026, 10, 1), 352, 48, 4000)):
            Reading.objects.create(meter=light, month=month, usage=Decimal(mine))
            Reading.objects.create(meter=other, month=month, usage=Decimal(theirs))
            MonthlyAmount.objects.create(receipt=split, month=month, amount=Decimal(total))
        h = services.meter_history(light, date(2026, 10, 5))
        sept, octo = h['rows']
        self.assertEqual((sept.was, sept.now, octo.was, octo.now), (12400, 12741, 12741, 13093))
        self.assertTrue(octo.price_from_receipt)
        self.assertEqual((sept.price, sept.total), (Decimal('9'), Decimal('3069.00')))
        self.assertEqual(octo.total, Decimal('3520.00'))
        self.assertTrue(h['by_usage'])

        # The window: from «Счётчики» (the cell and «…»), someone else's meter — 404.
        page = self.client.get(reverse('meter_list'))
        self.assertContains(page, reverse('meter_history', args=[water.pk]))
        window = self.client.get(reverse('meter_history', args=[water.pk]), HTTP_X_MODAL='1')
        self.assertContains(window, 'начальное 221')
        self.assertContains(window, '382,00')
        self.assertContains(window, 'не введено')
        stranger = Meter.objects.create(property=make_property(
            User.objects.create_user(username='e@example.ru', password='secret1')), kind='custom', name='Чужой')
        self.assertEqual(self.client.get(reverse('meter_history', args=[stranger.pk])).status_code, 404)

    def test_payment_receipts(self):
        # 2026-11-25: several services of one paper receipt — one tile on «Оплаты», made by dragging a tile onto
        # another (as apps into a folder on a phone). One sum, one check, one date: the tile dropped ONTO decides.
        octo = date(2026, 10, 1)
        MonthlyAmount.objects.create(receipt=self.receipt, month=octo, amount=Decimal('4200'))
        water = Receipt.objects.create(property=self.prop, kind='custom', name='Вода', amount_mode='fixed',
                                       fixed_amount=Decimal('540'))
        heat = Receipt.objects.create(property=self.prop, kind='custom', name='Подогрев', amount_mode='fixed',
                                      fixed_amount=Decimal('312'))
        sewage = Receipt.objects.create(property=self.prop, kind='custom', name='Водоотведение', amount_mode='fixed',
                                        fixed_amount=Decimal('855'))
        twin = Receipt.objects.create(property=self.prop, kind='custom', name='Водоотведение', amount_mode='fixed',
                                      fixed_amount=Decimal('5'))
        tiles = lambda: next(r for r in services.payment_table(self.user, octo)['rows'] if r['property'] == self.prop)['tiles']  # noqa: E731
        merge = reverse('payment_merge', args=['2026-10'])

        # Heating was paid on the 12th; water dropped onto it — the receipt is paid on the 12th, named «Квитанция».
        services.save_payment(heat, octo, date(2026, 10, 12))
        response = self.client.post(merge, {'src': f'r{water.pk}', 'dst': f'r{heat.pk}'})
        bundle = PayBundle.objects.get()
        self.assertEqual(response['X-Pay-Bundle'], str(bundle.pk))
        self.assertEqual(bundle.name, 'Квитанция')
        folder = tiles()[1]
        self.assertEqual([part['name'] for part in folder['parts']], ['Вода', 'Подогрев'])
        self.assertEqual((folder['amount'], folder['state'], folder['paid_on']), (Decimal('852.00'), 'paid', date(2026, 10, 12)))
        self.assertEqual(len(tiles()), 3, 'the folder stands where its first part stood')

        # Sewage (with its same-name twin) dropped onto the receipt: it joins, and takes the receipt's date.
        response = self.client.post(merge, {'src': f'r{sewage.pk}', 'dst': f'b{bundle.pk}'})
        self.assertFalse(response.has_header('X-Pay-Bundle'), 'nothing new made')
        self.assertEqual(twin.payments.get(month=octo).paid_on, date(2026, 10, 12))
        folder = tiles()[1]
        self.assertEqual((len(folder['parts']), folder['amount']), (3, Decimal('1712.00')))

        # The receipt dropped onto an unpaid service: all of it not paid; its parts pour into the new receipt.
        self.client.post(merge, {'src': f'b{bundle.pk}', 'dst': f'r{self.receipt.pk}'})
        self.assertFalse(PayBundle.objects.filter(pk=bundle.pk).exists())
        [folder] = tiles()
        self.assertEqual((len(folder['parts']), folder['state'], folder['name']), (4, 'due', 'Квитанция'))
        bundle = folder['bundle']

        # The check marks all; the name; «×» takes a service out; one left — the receipt is gone.
        self.client.post(reverse('payment_bundle_edit', args=[bundle.pk, '2026-10']), {'paid': '1', 'paid_on': '20.10.2026'})
        self.assertEqual(set(Payment.objects.filter(month=octo).values_list('paid_on', flat=True)), {date(2026, 10, 20)})
        url = reverse('payment_bundle', args=[bundle.pk])
        self.client.post(url, {'name': '  ЕИРЦ ', 'view': '2026-10'})
        self.assertEqual(tiles()[0]['name'], 'ЕИРЦ')
        self.client.post(url, {'out': sewage.pk, 'view': '2026-10'})
        self.assertEqual([tile['name'] for tile in tiles()], ['ЕИРЦ', 'Водоотведение'])
        self.assertIsNone(Receipt.objects.get(pk=twin.pk).pay_bundle_id, 'the twin comes out too')
        self.client.post(url, {'out': water.pk, 'view': '2026-10'})
        self.client.post(url, {'out': heat.pk, 'view': '2026-10'})
        self.assertFalse(PayBundle.objects.exists())
        self.assertEqual(len(tiles()), 4)

        # Two receipts never share a name; «Разъединить»; another object's tile can't be dropped here; POST only.
        services.merge_tiles(self.prop, octo, water, heat)
        services.merge_tiles(self.prop, octo, sewage, self.receipt)
        self.assertEqual(sorted(PayBundle.objects.values_list('name', flat=True)), ['Квитанция', 'Квитанция 2'])
        second = PayBundle.objects.get(name='Квитанция 2')
        self.client.post(reverse('payment_bundle', args=[second.pk]), {'split': '1'})
        self.assertEqual(PayBundle.objects.count(), 1)
        other = Property.objects.create(owner=self.user, name='Яблочная 2', kind='commercial')
        theirs = Receipt.objects.create(property=other, kind='custom', name='Свет')
        self.assertEqual(self.client.post(merge, {'src': f'r{theirs.pk}', 'dst': f'r{sewage.pk}'}).status_code, 400)
        stranger = Receipt.objects.create(property=make_property(
            User.objects.create_user(username='d@example.ru', password='secret1')), kind='custom', name='Чужая')
        self.assertEqual(self.client.post(merge, {'src': f'r{stranger.pk}', 'dst': f'r{sewage.pk}'}).status_code, 404)
        self.assertEqual(self.client.get(url).status_code, 405)
        page = self.client.get(reverse('payment_list') + '?month=2026-10')
        self.assertContains(page, 'is-folder')
        self.assertContains(page, 'data-pay-bundle-back')

    def test_live_save_returns_recalculated_page(self):
        response = self.client.post(
            reverse('month_save', args=[self.prop.pk]),
            {'month': '2026-09', f'amount-{self.receipt.pk}': '4200'},
            HTTP_X_LIVE='1',
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '1 890,00')   # Виктор: 4 200 × 45 %
        self.assertContains(response, 'id="obj-bill"')

    def test_plain_save_redirects_to_the_same_month(self):
        response = self.client.post(
            reverse('month_save', args=[self.prop.pk]),
            {'month': '2026-09', f'amount-{self.receipt.pk}': '4200'},
        )
        self.assertRedirects(response, reverse('property_detail', args=[self.prop.pk]) + '?month=2026-09')
        page = self.client.get(response['Location'])
        self.assertContains(page, 'value="4 200"')

    def test_beacon_save(self):
        response = self.client.post(
            reverse('month_save', args=[self.prop.pk]),
            {'month': '2026-09', f'amount-{self.receipt.pk}': '100', 'beacon': '1'},
        )
        self.assertEqual(response.status_code, 204)

    def test_selected_tenant(self):
        url = reverse('property_detail', args=[self.prop.pk])
        self.assertEqual(self.client.get(url).context['selected_tenant'], self.viktor.pk)
        self.assertEqual(self.client.get(url, {'tenant': self.vlad.pk}).context['selected_tenant'], self.vlad.pk)
        self.assertEqual(self.client.get(url, {'tenant': 'junk'}).context['selected_tenant'], self.viktor.pk)

    def test_other_landlord_cannot_save(self):
        other = User.objects.create_user(username='b@example.ru', email='b@example.ru', password='secret1')
        self.client.force_login(other)
        response = self.client.post(reverse('month_save', args=[self.prop.pk]), {'month': '2026-09'})
        self.assertEqual(response.status_code, 404)


class ServicesSectionTests(TestCase):
    """«Услуги» in the menu: the table of all services and «+ Добавить услугу»."""

    def setUp(self):
        self.user = User.objects.create_user(username='a@example.ru', email='a@example.ru', password='secret1')
        self.client.force_login(self.user)

    def test_services_label(self):
        self.assertEqual(services.services_label(0), 'нет услуг')
        self.assertEqual(services.services_label(1), '1 услуга')
        self.assertEqual(services.services_label(3), '3 услуги')
        self.assertEqual(services.services_label(5), '5 услуг')
        self.assertEqual(services.services_label(11), '11 услуг')
        self.assertEqual(services.services_label(22), '22 услуги')

    def test_table_lists_services_of_all_own_objects(self):
        first = make_property(self.user)
        second = Property.objects.create(owner=self.user, name='Ленина 5')
        Receipt.objects.create(property=first, kind='electricity', name='Свет', metered=True, unit='кВт·ч', split='meters')
        Receipt.objects.create(property=second, kind='internet', name='Интернет', split='equal',
                               amount_mode='fixed', fixed_amount=Decimal('600'))
        stranger = User.objects.create_user(username='b@example.ru', email='b@example.ru', password='secret1')
        Receipt.objects.create(property=make_property(stranger), name='Чужая услуга')

        response = self.client.get(reverse('receipt_list'))
        self.assertContains(response, 'Свет')
        self.assertContains(response, 'у арендаторов, кВт·ч')
        self.assertContains(response, 'Интернет')
        self.assertContains(response, '600,00')
        self.assertContains(response, 'Ленина 5')
        self.assertNotContains(response, 'Чужая услуга')
        self.assertContains(response, '<span class="nav-count">2</span>')

    def test_empty_table(self):
        self.assertContains(self.client.get(reverse('receipt_list')), 'Услуг пока нет')

    def test_add_with_one_object_goes_straight_to_kinds(self):
        prop = make_property(self.user)
        response = self.client.get(reverse('receipt_add'), HTTP_X_MODAL='1')
        self.assertTemplateUsed(response, 'billing/_service_window.html')
        self.assertContains(response, reverse('service_save', args=[prop.pk]))

    def test_add_with_several_objects_asks_which(self):
        first = make_property(self.user)
        second = Property.objects.create(owner=self.user, name='Ленина 5')
        Receipt.objects.create(property=first, name='Свет')
        response = self.client.get(reverse('receipt_add'), HTTP_X_MODAL='1')
        self.assertContains(response, 'К какому объекту?')
        self.assertContains(response, reverse('service_window', args=[first.pk]))
        self.assertContains(response, reverse('service_window', args=[second.pk]))
        self.assertContains(response, '1 услуга')
        self.assertContains(response, 'нет услуг')

    def test_add_without_objects_offers_an_object(self):
        response = self.client.get(reverse('receipt_add'), HTTP_X_MODAL='1')
        self.assertContains(response, reverse('property_create'))

    def test_card_menu_has_no_add_items(self):
        # 2026-11-16: «Добавить арендатора / услугу» are on the card itself, not in its «…» menu.
        prop = make_property(self.user)
        response = self.client.get(reverse('property_list'))
        self.assertNotContains(response, f'href="{reverse("service_window", args=[prop.pk])}" data-modal class="dropdown-item')

    def test_saving_from_the_table_returns_to_the_table(self):
        receipt = Receipt.objects.create(property=make_property(self.user), name='Свет')
        response = self.client.post(
            reverse('receipt_delete', args=[receipt.pk]),
            HTTP_X_MODAL='1', HTTP_REFERER='http://testserver/services/?x=1',
        )
        self.assertEqual(response['X-Modal-Redirect'], '/services/?x=1')

    def test_foreign_referer_is_ignored(self):
        prop = make_property(self.user)
        receipt = Receipt.objects.create(property=prop, name='Свет')
        response = self.client.post(
            reverse('receipt_delete', args=[receipt.pk]),
            HTTP_X_MODAL='1', HTTP_REFERER='https://evil.example/services/',
        )
        self.assertEqual(response['X-Modal-Redirect'], reverse('property_detail', args=[prop.pk]))
