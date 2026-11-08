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
        self.assertEqual(light.name, 'Свет')
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

    def test_metered_but_split_by_shares_has_one_common_meter(self):
        receipt = services.new_receipt(self.prop, 'water')
        receipt.split = Receipt.Split.SHARES
        services.save_receipt(receipt)
        meters = list(receipt.meters.all())
        self.assertEqual(len(meters), 1)
        self.assertIsNone(meters[0].tenant)

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
        self.assertContains(response, 'Какие квитанции приходят по объекту?')
        self.assertContains(response, reverse('receipt_create', args=[self.prop.pk]) + '?kind=electricity')

    def test_create_form_is_prefilled_from_preset(self):
        url = reverse('receipt_create', args=[self.prop.pk]) + '?kind=electricity'
        response = self.client.get(url, HTTP_X_MODAL='1')
        self.assertContains(response, 'value="Свет"')
        self.assertContains(response, 'name="split" value="meters" checked')

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
        self.assertContains(page, reverse('receipt_pick', args=[self.prop.pk]))

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

    def test_picker(self):
        response = self.client.get(reverse('receipt_pick', args=[self.prop.pk]), HTTP_X_MODAL='1')
        self.assertContains(response, '?kind=electricity')
        self.assertNotContains(response, '?kind=management')  # already added
        self.assertContains(response, '?kind=custom')

    def test_other_landlord_cannot_save(self):
        other = User.objects.create_user(username='b@example.ru', email='b@example.ru', password='secret1')
        self.client.force_login(other)
        response = self.client.post(reverse('month_save', args=[self.prop.pk]), {'month': '2026-09'})
        self.assertEqual(response.status_code, 404)
