from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.properties.models import Property
from apps.properties.services import setup_steps
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
        self.assertEqual(sorted(receipt.meters.values_list('name', flat=True)), ['Виктор', 'Владислав', 'Общий счётчик'])
        self.assertEqual(receipt.split, Receipt.Split.METERS)

    def test_single_rate_drops_the_night_tariff(self):
        receipt = services.new_receipt(self.prop, 'electricity')
        receipt.tariff, receipt.tariff_night = Decimal('7'), Decimal('3')
        services.save_receipt(receipt)
        self.assertIsNone(receipt.tariff_night)

    def test_meter_numbers_and_starting_readings(self):
        receipt = services.new_receipt(self.prop, 'electricity')
        services.save_receipt(receipt, meter_details={
            self.viktor.pk: {'serial': '0123', 'initial': Decimal('1000'), 'initial_night': None},
        })
        meter = receipt.meters.get(tenant=self.viktor)
        self.assertEqual((meter.serial, meter.initial), ('0123', Decimal('1000')))

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

    def test_meters_follow_tenant_changes(self):
        receipt = services.save_receipt(services.new_receipt(self.prop, 'electricity'))
        kept_meter = receipt.meters.get(tenant=self.viktor)

        self.vlad.delete()
        Tenant.objects.create(property=self.prop, name='Ольга', share_percent=Decimal('55'))
        services.resync_property(self.prop)

        self.assertEqual(sorted(receipt.meters.values_list('name', flat=True)), ['Виктор', 'Ольга'])
        self.assertTrue(Meter.objects.filter(pk=kept_meter.pk).exists(), 'existing meter keeps its history')

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
        sewage.meters.add(shared)

        services.delete_receipt(water)
        self.assertTrue(Meter.objects.filter(pk=shared.pk).exists(), 'still used by sewage')
        self.assertFalse(Meter.objects.filter(tenant=self.vlad, kind='water').exists(), 'unused meter goes away')

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
        url = reverse('receipt_create', args=[self.prop.pk]) + '?kind=electricity'
        response = self.client.get(url, HTTP_X_MODAL='1')
        self.assertContains(response, 'value="Электричество"')
        self.assertContains(response, 'name="layout" value="tenants" checked')
        self.assertContains(response, 'data-pick-value="кВт·ч"')

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

    def test_metered_service_needs_tariff_and_night_tariff(self):
        url = reverse('receipt_create', args=[self.prop.pk])
        data = {'kind': 'electricity', 'name': 'Свет', 'metered': '1', 'zones': '2', 'unit': 'кВт·ч',
                'layout': 'tenants', 'amount_mode': 'monthly', 'tariff': '7,20'}
        response = self.client.post(url, data, HTTP_X_MODAL='1')
        self.assertContains(response, 'Укажите ночной тариф')
        self.assertFalse(self.prop.receipts.exists())

        tenant = self.prop.tenants.get()
        data.update({'tariff_night': '3,10', f'serial-t{tenant.pk}': '0123456', f'initial-t{tenant.pk}': '1 000',
                     f'initialn-t{tenant.pk}': '400'})
        response = self.client.post(url, data, HTTP_X_MODAL='1')
        self.assertEqual(response.status_code, 204)
        receipt = self.prop.receipts.get()
        self.assertEqual((receipt.zones, receipt.tariff_night, receipt.split), (2, Decimal('3.1'), 'meters'))
        meter = receipt.meters.get()
        self.assertEqual((meter.serial, meter.initial, meter.initial_night), ('0123456', Decimal('1000'), Decimal('400')))

        response = self.client.get(reverse('receipt_edit', args=[receipt.pk]), HTTP_X_MODAL='1')
        self.assertContains(response, 'data-state="locked"')
        self.assertContains(response, 'value="0123456" maxlength="50"')

    def test_meter_question_is_rendered_yes_for_a_metered_preset(self):
        url = reverse('receipt_create', args=[self.prop.pk]) + '?kind=electricity'
        response = self.client.get(url, HTTP_X_MODAL='1')
        self.assertContains(response, 'name="metered" value="1" checked')
        self.assertNotContains(response, 'name="split" value="meters"')

    def test_usage_mode_is_saved_and_the_object_page_asks_for_usage(self):
        response = self.client.post(
            reverse('receipt_create', args=[self.prop.pk]),
            {'kind': 'electricity', 'name': 'Свет', 'metered': '1', 'unit': 'кВт·ч', 'tariff': '5',
             'input_mode': 'usage', 'layout': 'common', 'split': 'shares', 'amount_mode': 'monthly'},
            HTTP_X_MODAL='1',
        )
        self.assertEqual(response.status_code, 204)
        receipt = self.prop.receipts.get(name='Свет')
        self.assertEqual(receipt.input_mode, Receipt.InputMode.USAGE)
        meter = receipt.meters.get()
        page = self.client.get(reverse('property_detail', args=[self.prop.pk]))
        self.assertContains(page, f'name="use-{meter.pk}"')
        self.assertNotContains(page, f'name="cur-{meter.pk}"')

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
