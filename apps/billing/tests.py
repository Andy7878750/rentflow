from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.properties.models import Property
from apps.properties.services import free_meters, setup_steps
from apps.tenants.models import Tenant

from . import services
from .models import Meter, Receipt

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
        # The menu: electricity and water only, and «Счётчик» (nobody's name) is not an own variant.
        self.meter(kind='custom', name='')
        services.save_meter(self.prop, {'kind': 'custom', 'name': ''})
        names = [option['name'] for option in services.meter_kind_options(self.prop)]
        self.assertEqual(names, ['Электричество', 'Вода холодная', 'Вода горячая', 'Полив'])

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
        self.assertContains(response, reverse('receipt_create', args=[self.prop.pk]) + '?kind=electricity')

    def test_create_form_is_prefilled_from_preset(self):
        light = Meter.objects.create(property=self.prop, kind='electricity', name='Электричество', unit='кВт·ч')
        Meter.objects.create(property=self.prop, kind='water', name='Вода холодная', unit='м³')
        url = reverse('receipt_create', args=[self.prop.pk]) + '?kind=electricity'
        response = self.client.get(url, HTTP_X_MODAL='1')
        self.assertContains(response, 'value="Электричество"')
        # The object's meters as tiles: the template ticks its own kind only.
        self.assertContains(response, f'name="meter_ids" value="{light.pk}" checked')
        self.assertContains(response, 'name="meter_ids" value="', count=2)
        self.assertContains(response, 'value="common" aria-label="Общий на объект" checked', msg_prefix='a common meter')
        self.assertContains(response, 'data-meter-count>1 счётчик<')

    def test_create_in_modal(self):
        response = self.client.post(
            reverse('receipt_create', args=[self.prop.pk]),
            {'kind': 'internet', 'name': 'Интернет', 'provider': 'Ростелеком', 'metered': '0',
             'split': 'equal', 'amount_mode': 'fixed', 'fixed_amount': '600,00'},
            HTTP_X_MODAL='1',
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response['X-Modal-Redirect'], reverse('property_detail', args=[self.prop.pk]))
        receipt = self.prop.receipts.get()
        self.assertEqual(receipt.fixed_amount, Decimal('600.00'))
        self.assertEqual(receipt.kind, 'internet')

        page = self.client.get(reverse('property_detail', args=[self.prop.pk]))
        self.assertContains(page, 'Интернет')
        self.assertContains(page, reverse('receipt_create', args=[self.prop.pk]))

    def test_metered_service_needs_ticked_meters_and_their_tariffs(self):
        url = reverse('receipt_create', args=[self.prop.pk])
        tenant = self.prop.tenants.get()
        light = Meter.objects.create(property=self.prop, kind='electricity', name='Электричество', unit='кВт·ч',
                                     tenant=tenant, day_night=True, serial='0123456')
        data = {'kind': 'electricity', 'name': '', 'metered': '1', 'amount_mode': 'monthly', 'meters_shown': '1',
                'tariff_key': 'electricity', 'tariff_day': '7,20', 'tariff_nightv': ''}
        response = self.client.post(url, data, HTTP_X_MODAL='1')
        self.assertContains(response, 'Отметьте счётчики')
        self.assertFalse(self.prop.receipts.exists())

        data['meter_ids'] = str(light.pk)
        response = self.client.post(url, data, HTTP_X_MODAL='1')
        self.assertContains(response, 'Укажите тариф', msg_prefix='a day / night meter needs the night tariff')
        self.assertFalse(self.prop.receipts.exists())

        data['tariff_nightv'] = '3,10'
        response = self.client.post(url, data, HTTP_X_MODAL='1')
        self.assertEqual(response.status_code, 204)
        receipt = self.prop.receipts.get()
        self.assertEqual(receipt.name, 'Электричество', "an empty name — the template's")
        self.assertEqual((receipt.zones, receipt.unit, receipt.split), (2, 'кВт·ч', 'meters'))
        self.assertEqual(list(receipt.meters.all()), [light])
        row = receipt.tariffs.get()
        self.assertEqual((row.key, row.tariff, row.tariff_night), ('electricity', Decimal('7.2'), Decimal('3.1')))

        response = self.client.get(reverse('receipt_edit', args=[receipt.pk]), HTTP_X_MODAL='1')
        self.assertContains(response, f'name="meter_ids" value="{light.pk}" checked')
        self.assertContains(response, 'name="tariff_day" value="7,2"')
        self.assertContains(response, 'name="tariff_nightv" value="3,1"')

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

    def test_meter_question_is_rendered_yes_for_a_metered_preset(self):
        url = reverse('receipt_create', args=[self.prop.pk]) + '?kind=electricity'
        response = self.client.get(url, HTTP_X_MODAL='1')
        self.assertContains(response, 'name="metered" value="1" checked')
        self.assertNotContains(response, 'name="split" value="meters"')

    def test_meters_block_without_object_meters_points_to_the_object(self):
        url = reverse('receipt_create', args=[self.prop.pk]) + '?kind=water'
        response = self.client.get(url, HTTP_X_MODAL='1')
        self.assertContains(response, 'data-meter-count>0 счётчиков<')
        self.assertContains(response, 'У объекта пока нет счётчиков')
        self.assertContains(response, '+ Добавить счётчик объекта')
        self.assertContains(response, reverse('property_edit', args=[self.prop.pk]))

    def test_usage_mode_is_saved_and_the_object_page_asks_for_usage(self):
        meter = Meter.objects.create(property=self.prop, kind='electricity', name='Электричество', unit='кВт·ч')
        response = self.client.post(
            reverse('receipt_create', args=[self.prop.pk]),
            {'kind': 'electricity', 'name': 'Свет', 'metered': '1', 'input_mode': 'usage', 'layout': 'common',
             'split': 'shares', 'amount_mode': 'monthly', 'meters_shown': '1', 'meter_ids': str(meter.pk),
             'tariff_key': 'electricity', 'tariff_day': '5', 'tariff_nightv': ''},
            HTTP_X_MODAL='1',
        )
        self.assertEqual(response.status_code, 204)
        receipt = self.prop.receipts.get(name='Свет')
        self.assertEqual(receipt.input_mode, Receipt.InputMode.USAGE)
        page = self.client.get(reverse('property_detail', args=[self.prop.pk]))
        self.assertContains(page, f'name="use-{meter.pk}"')
        self.assertNotContains(page, f'name="cur-{meter.pk}"')
        self.assertContains(page, 'Тариф 5 ₽ за кВт·ч')

    def test_fixed_amount_is_required(self):
        response = self.client.post(
            reverse('receipt_create', args=[self.prop.pk]),
            {'kind': 'internet', 'name': 'Интернет', 'metered': '0', 'split': 'equal', 'amount_mode': 'fixed'},
            HTTP_X_MODAL='1',
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Укажите сумму')
        self.assertFalse(self.prop.receipts.exists())

    def test_edit_and_delete(self):
        receipt = services.save_receipt(services.new_receipt(self.prop, 'management'))
        response = self.client.post(
            reverse('receipt_edit', args=[receipt.pk]),
            {'name': 'Содержание и ремонт', 'metered': '0', 'split': 'area', 'amount_mode': 'monthly'},
        )
        self.assertRedirects(response, reverse('property_detail', args=[self.prop.pk]))
        receipt.refresh_from_db()
        self.assertEqual(receipt.name, 'Содержание и ремонт')
        self.assertEqual(receipt.split, 'area')

        self.client.post(reverse('receipt_delete', args=[receipt.pk]))
        self.assertFalse(Receipt.objects.filter(pk=receipt.pk).exists())

    def test_other_landlords_receipts_are_not_reachable(self):
        foreign_prop = make_property(self.other)
        foreign = services.save_receipt(services.new_receipt(foreign_prop, 'management'))
        self.assertEqual(self.client.get(reverse('receipt_create', args=[foreign_prop.pk])).status_code, 404)
        for name in ('receipt_edit', 'receipt_delete'):
            self.assertEqual(self.client.get(reverse(name, args=[foreign.pk])).status_code, 404, name)
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

    def test_new_service_window_has_templates_on_top(self):
        response = self.client.get(reverse('receipt_create', args=[self.prop.pk]), HTTP_X_MODAL='1')
        self.assertContains(response, 'data-kind-strip')  # templates as one row of chips on top
        self.assertContains(response, '?kind=electricity')
        self.assertContains(response, '?kind=heating')
        self.assertContains(response, 'kind-tile-mark')  # «УК» is already there: marked, still offered
        self.assertContains(response, 'kind-tile-own is-selected')  # nothing picked yet: «Своя»
        self.assertContains(response, 'name="split"')  # and the settings in the same window
        self.assertContains(response, 'Королева 61 ·')  # who shares it, under the title

    def test_template_from_object_page_opens_picked(self):
        response = self.client.get(reverse('receipt_create', args=[self.prop.pk]) + '?kind=water', HTTP_X_MODAL='1')
        self.assertContains(response, 'kind-tile is-selected" aria-current="true"')
        self.assertContains(response, 'value="Вода холодная"')

    def test_editing_has_no_templates(self):
        receipt = self.prop.receipts.first()
        response = self.client.get(reverse('receipt_edit', args=[receipt.pk]), HTTP_X_MODAL='1')
        self.assertNotContains(response, 'kind-tiles')

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
        self.assertTemplateUsed(response, 'billing/_receipt_form.html')
        self.assertContains(response, reverse('receipt_create', args=[prop.pk]) + '?kind=electricity')

    def test_add_with_several_objects_asks_which(self):
        first = make_property(self.user)
        second = Property.objects.create(owner=self.user, name='Ленина 5')
        Receipt.objects.create(property=first, name='Свет')
        response = self.client.get(reverse('receipt_add'), HTTP_X_MODAL='1')
        self.assertContains(response, 'К какому объекту?')
        self.assertContains(response, reverse('receipt_create', args=[first.pk]))
        self.assertContains(response, reverse('receipt_create', args=[second.pk]))
        self.assertContains(response, '1 услуга')
        self.assertContains(response, 'нет услуг')

    def test_add_without_objects_offers_an_object(self):
        response = self.client.get(reverse('receipt_add'), HTTP_X_MODAL='1')
        self.assertContains(response, reverse('property_create'))

    def test_card_menu_has_add_service(self):
        prop = make_property(self.user)
        response = self.client.get(reverse('property_list'))
        self.assertContains(response, f'href="{reverse("receipt_create", args=[prop.pk])}" data-modal class="dropdown-item')

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
