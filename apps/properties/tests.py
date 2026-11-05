import datetime

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from . import services
from .models import Property

User = get_user_model()


class MonthServiceTests(SimpleTestCase):
    def test_parse_valid_month(self):
        self.assertEqual(services.parse_month('2026-10'), datetime.date(2026, 10, 1))

    def test_parse_falls_back_to_current_month(self):
        today = datetime.date(2026, 11, 5)
        for bad in (None, '', 'abc', '2026-13', '2026'):
            self.assertEqual(services.parse_month(bad, today=today), datetime.date(2026, 11, 1), bad)

    def test_shift_month_across_years(self):
        self.assertEqual(services.shift_month(datetime.date(2026, 1, 1), -1), datetime.date(2025, 12, 1))
        self.assertEqual(services.shift_month(datetime.date(2026, 12, 1), 1), datetime.date(2027, 1, 1))

    def test_labels(self):
        month = datetime.date(2026, 10, 1)
        self.assertEqual(services.month_param(month), '2026-10')
        self.assertEqual(services.month_label(month), 'Октябрь 2026')


class PropertyPagesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='a@example.ru', email='a@example.ru', password='secret1')
        self.other = User.objects.create_user(username='b@example.ru', email='b@example.ru', password='secret1')

    def test_home_redirects_to_objects(self):
        self.client.force_login(self.user)
        self.assertRedirects(self.client.get(reverse('home')), reverse('property_list'))

    def test_list_requires_login(self):
        response = self.client.get(reverse('property_list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('account_login'), response['Location'])

    def test_list_shows_only_own_objects(self):
        Property.objects.create(owner=self.user, name='Королева 61', address='СПб')
        Property.objects.create(owner=self.other, name='Чужой объект', address='Москва')
        self.client.force_login(self.user)

        response = self.client.get(reverse('property_list'))

        self.assertContains(response, 'Королева 61')
        self.assertNotContains(response, 'Чужой объект')

    def test_list_month_switcher(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('property_list'), {'month': '2026-01'})
        self.assertContains(response, 'Январь 2026')
        self.assertContains(response, '?month=2025-12')
        self.assertContains(response, '?month=2026-02')

    def test_create_assigns_owner(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('property_create'), {
            'name': 'Глинки 148',
            'kind': 'apartment',
            'address': 'г. Пушкин',
            'management_company': 'ТСЖ «Глинки 16»',
            'management_phone': '+7 (931) 244-68-38',
        })

        self.assertRedirects(response, reverse('property_list'))
        prop = Property.objects.get(name='Глинки 148')
        self.assertEqual(prop.owner, self.user)
        self.assertEqual(prop.phone_href, '+79312446838')


class PropertyActionsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='a@example.ru', email='a@example.ru', password='secret1')
        self.other = User.objects.create_user(username='b@example.ru', email='b@example.ru', password='secret1')
        self.prop = Property.objects.create(owner=self.user, name='Королева 61', kind='commercial', address='СПб')
        self.client.force_login(self.user)

    def test_card_menu_links(self):
        response = self.client.get(reverse('property_list'))
        for name in ('property_detail', 'property_edit', 'property_delete'):
            self.assertContains(response, reverse(name, args=[self.prop.pk]))

    def test_detail(self):
        response = self.client.get(reverse('property_detail', args=[self.prop.pk]))
        self.assertContains(response, 'Королева 61')
        self.assertContains(response, 'Нежилое помещение')

    def test_edit(self):
        url = reverse('property_edit', args=[self.prop.pk])
        self.assertContains(self.client.get(url), 'value="commercial" selected')

        response = self.client.post(url, {'name': 'Королёва 61', 'kind': 'commercial', 'address': 'СПб'})

        self.assertRedirects(response, reverse('property_detail', args=[self.prop.pk]))
        self.prop.refresh_from_db()
        self.assertEqual(self.prop.name, 'Королёва 61')

    def test_delete_needs_confirmation(self):
        url = reverse('property_delete', args=[self.prop.pk])
        self.assertContains(self.client.get(url), 'Удалить объект')
        self.assertTrue(Property.objects.filter(pk=self.prop.pk).exists())

        self.assertRedirects(self.client.post(url), reverse('property_list'))
        self.assertFalse(Property.objects.filter(pk=self.prop.pk).exists())

    def test_other_landlords_object_is_not_reachable(self):
        foreign = Property.objects.create(owner=self.other, name='Чужой', address='Москва')
        for name in ('property_detail', 'property_edit', 'property_delete'):
            self.assertEqual(self.client.get(reverse(name, args=[foreign.pk])).status_code, 404, name)
        self.client.post(reverse('property_delete', args=[foreign.pk]))
        self.assertTrue(Property.objects.filter(pk=foreign.pk).exists())
