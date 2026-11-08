import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.tenants.models import Tenant

from . import services
from .models import Property, PropertyKind

User = get_user_model()


def form_data(tenants=(), initial_forms=0, **fields):
    """POST body for the object form: object fields plus the tenants formset."""
    data = {
        'name': 'Глинки 148',
        'kind': 'apartment',
        'occupancy': 'tenants',
        'share_unit': 'percent',
        'tenants-TOTAL_FORMS': str(len(tenants)),
        'tenants-INITIAL_FORMS': str(initial_forms),
        'tenants-MIN_NUM_FORMS': '0',
        'tenants-MAX_NUM_FORMS': '1000',
    }
    data.update(fields)
    for index, tenant in enumerate(tenants):
        for key, value in tenant.items():
            data[f'tenants-{index}-{key}'] = value
    return data


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


class SetupStepsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='a@example.ru', email='a@example.ru', password='secret1')

    def test_new_object_without_tenants_is_1_of_3(self):
        prop = Property.objects.create(owner=self.user, name='Глинки 148')
        setup = services.setup_steps(prop)
        self.assertEqual((setup['done'], setup['total'], setup['complete']), (1, 3, False))

    def test_tenants_step_done_when_tenants_exist(self):
        prop = Property.objects.create(owner=self.user, name='Глинки 148')
        Tenant.objects.create(property=prop, name='Иванов')
        setup = services.setup_steps(prop)
        self.assertEqual(setup['done'], 2)
        self.assertEqual(setup['steps'][1], {'label': 'Арендаторы', 'done': True})

    def test_owner_used_object_counts_people_step_done(self):
        prop = Property.objects.create(owner=self.user, name='Дача', occupancy=Property.Occupancy.OWNER)
        setup = services.setup_steps(prop)
        self.assertEqual(setup['steps'][1], {'label': 'Собственник', 'done': True})
        self.assertEqual(setup['done'], 2)

    def test_list_card_shows_setup_checklist(self):
        Property.objects.create(owner=self.user, name='Глинки 148')
        self.client.force_login(self.user)
        response = self.client.get(reverse('property_list'))
        self.assertContains(response, 'Настройка 1 из 3')
        self.assertContains(response, 'Добавить услуги')


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
        response = self.client.post(reverse('property_create'), form_data(
            address='г. Пушкин',
            management_company='ТСЖ «Глинки 16»',
            management_phone='+7 (931) 244-68-38',
        ))

        prop = Property.objects.get(name='Глинки 148')
        self.assertRedirects(response, reverse('property_list'), fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse('property_list')), 'Объект «Глинки 148» создан.')
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

    def test_detail_in_modal_is_summary_card(self):
        self.prop.tenants.create(name='Виктор', share_percent=45, phone='+7 (904) 648-30-57')
        url = reverse('property_detail', args=[self.prop.pk])
        response = self.client.get(url, headers={'X-Modal': '1'})
        self.assertTemplateUsed(response, 'properties/_summary.html')
        self.assertContains(response, 'Виктор')
        self.assertContains(response, '45%')
        self.assertContains(response, 'href="tel:+79046483057"')
        self.assertContains(response, reverse('property_edit', args=[self.prop.pk]))
        self.assertNotContains(response, '<html')

    def test_other_users_summary_is_hidden(self):
        prop = Property.objects.create(owner=self.other, name='Чужой')
        response = self.client.get(reverse('property_detail', args=[prop.pk]), headers={'X-Modal': '1'})
        self.assertEqual(response.status_code, 404)

    def test_edit(self):
        url = reverse('property_edit', args=[self.prop.pk])
        page = self.client.get(url)
        self.assertContains(page, 'name="kind" value="commercial"')
        self.assertContains(page, 'Нежилое помещение')

        response = self.client.post(url, form_data(name='Королёва 61', kind='commercial', address='СПб'))

        self.assertRedirects(response, reverse('property_list'))
        self.prop.refresh_from_db()
        self.assertEqual(self.prop.name, 'Королёва 61')

    def test_delete_needs_confirmation(self):
        url = reverse('property_delete', args=[self.prop.pk])
        self.assertContains(self.client.get(url), 'Удалить объект')
        self.assertTrue(Property.objects.filter(pk=self.prop.pk).exists())

        self.assertRedirects(self.client.post(url), reverse('property_list'))
        self.assertFalse(Property.objects.filter(pk=self.prop.pk).exists())

    def test_delete_in_modal(self):
        self.prop.tenants.create(name='Виктор', share_percent=45)
        url = reverse('property_delete', args=[self.prop.pk])
        page = self.client.get(url, headers={'X-Modal': '1'})
        self.assertTemplateUsed(page, 'properties/_delete.html')
        self.assertContains(page, 'арендаторы (1)')
        self.assertTrue(Property.objects.filter(pk=self.prop.pk).exists())

        response = self.client.post(url, headers={'X-Modal': '1'})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.headers['X-Modal-Redirect'], reverse('property_list'))
        self.assertFalse(Property.objects.filter(pk=self.prop.pk).exists())

    def test_other_landlords_object_is_not_reachable(self):
        foreign = Property.objects.create(owner=self.other, name='Чужой', address='Москва')
        for name in ('property_detail', 'property_edit', 'property_delete'):
            self.assertEqual(self.client.get(reverse(name, args=[foreign.pk])).status_code, 404, name)
        self.client.post(reverse('property_delete', args=[foreign.pk]))
        self.assertTrue(Property.objects.filter(pk=foreign.pk).exists())


class PropertyFormWithTenantsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='a@example.ru', email='a@example.ru', password='secret1')
        self.client.force_login(self.user)
        self.url = reverse('property_create')

    def test_form_does_not_invite_browser_autofill(self):
        # A password field would make the browser fill in the landlord's own login.
        html = self.client.get(self.url).content.decode()
        self.assertNotIn('type="password"', html)
        self.assertIn('class="masked"', html)
        self.assertIn('autocomplete="off"', html)

    def test_form_page_has_both_blocks(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'Объект и УК / ТСЖ')
        self.assertContains(response, 'Кто пользуется объектом')
        self.assertContains(response, 'Создать объект')

    def test_modal_request_gets_bare_form(self):
        response = self.client.get(self.url, headers={'X-Modal': '1'})
        self.assertContains(response, 'Новый объект')
        self.assertNotContains(response, 'app-sidebar')

    def test_create_with_percent_shares(self):
        self.client.post(self.url, form_data(area='60', tenants=[
            {'name': 'Виктор «Эгоист»', 'share': '45'},
            {'name': 'Владислав «Кофе»', 'share': '55', 'email': 'v@example.ru'},
        ]))

        prop = Property.objects.get()
        viktor, vlad = prop.tenants.all()
        self.assertEqual(viktor.share_percent, Decimal('45'))
        self.assertEqual(viktor.area, Decimal('27.00'))
        self.assertEqual(vlad.email, 'v@example.ru')

    def test_create_with_area_shares_derives_percent(self):
        self.client.post(self.url, form_data(area='60', share_unit='area', tenants=[
            {'name': 'Виктор', 'share': '27,5'},
        ]))

        tenant = Tenant.objects.get()
        self.assertEqual(tenant.area, Decimal('27.5'))
        self.assertEqual(tenant.share_percent, Decimal('45.83'))
        self.assertEqual(Property.objects.get().share_unit, 'area')

    def test_area_shares_need_object_area(self):
        response = self.client.post(self.url, form_data(share_unit='area', tenants=[
            {'name': 'Виктор', 'share': '27'},
        ]))
        self.assertContains(response, 'заполните площадь объекта')
        self.assertFalse(Property.objects.exists())

    def test_shares_over_100_percent_rejected(self):
        response = self.client.post(self.url, form_data(tenants=[
            {'name': 'А', 'share': '60'},
            {'name': 'Б', 'share': '50'},
        ]))
        self.assertContains(response, 'больше 100%')
        self.assertFalse(Property.objects.exists())

    def test_tenant_needs_name_and_share(self):
        response = self.client.post(self.url, form_data(tenants=[{'phone': '+7 900 000-00-00'}]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Property.objects.exists())

    def test_empty_tenant_row_is_ignored(self):
        self.client.post(self.url, form_data(tenants=[{'name': '', 'share': ''}]))
        self.assertEqual(Property.objects.count(), 1)
        self.assertFalse(Tenant.objects.exists())

    def test_owner_mode_ignores_tenant_rows(self):
        self.client.post(self.url, form_data(occupancy='owner', tenants=[{'phone': 'junk'}]))
        prop = Property.objects.get()
        self.assertTrue(prop.is_owner_used)
        self.assertFalse(prop.tenants.exists())

    def test_create_in_modal_shows_next_step(self):
        response = self.client.post(self.url, form_data(), headers={'X-Modal': '1'})
        prop = Property.objects.get()
        self.assertTemplateUsed(response, 'properties/_created.html')
        self.assertContains(response, 'Остался один шаг')
        self.assertContains(response, f'href="{reverse("property_detail", args=[prop.pk])}#receipts"')
        self.assertContains(response, f'href="{reverse("property_list")}"')

    def test_edit_in_modal_returns_redirect_header(self):
        prop = Property.objects.create(owner=self.user, name='Королёва 61')
        url = reverse('property_edit', args=[prop.pk])
        response = self.client.post(url, form_data(name='Королёва 61'), headers={'X-Modal': '1'})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response['X-Modal-Redirect'], reverse('property_list'))

    def test_sidebar_has_services_under_objects(self):
        html = self.client.get(reverse('property_list')).content.decode()
        item = '<span>Услуги</span>'
        self.assertIn(item, html)
        self.assertLess(html.index('Все объекты'), html.index(item))
        self.assertLess(html.index(item), html.index('<span>Счета</span>'))

    def test_edit_updates_and_removes_tenants(self):
        prop = Property.objects.create(owner=self.user, name='Королёва 61', area=Decimal('100'))
        keep = Tenant.objects.create(property=prop, name='Виктор', share_percent=Decimal('45'))
        drop = Tenant.objects.create(property=prop, name='Владислав', share_percent=Decimal('55'))
        url = reverse('property_edit', args=[prop.pk])

        page = self.client.get(url)
        self.assertContains(page, 'value="45"')
        self.assertContains(page, 'value="100"')  # not "100,00" or "1E+2"

        self.client.post(url, form_data(name='Королёва 61', area='100', initial_forms=2, tenants=[
            {'id': str(keep.pk), 'name': 'Виктор', 'share': '50'},
            {'id': str(drop.pk), 'name': 'Владислав', 'share': '55', 'DELETE': 'on'},
        ]))

        self.assertEqual(list(prop.tenants.values_list('name', flat=True)), ['Виктор'])
        keep.refresh_from_db()
        self.assertEqual(keep.share_percent, Decimal('50'))
        self.assertEqual(keep.area, Decimal('50.00'))

    def test_switching_to_owner_removes_tenants(self):
        prop = Property.objects.create(owner=self.user, name='Глинки 148')
        Tenant.objects.create(property=prop, name='Виктор', share_percent=Decimal('45'))
        self.client.post(reverse('property_edit', args=[prop.pk]), form_data(occupancy='owner'))
        self.assertFalse(prop.tenants.exists())

    def test_card_lists_tenants_with_shares(self):
        prop = Property.objects.create(owner=self.user, name='Королёва 61')
        Tenant.objects.create(property=prop, name='Виктор «Эгоист»', share_percent=Decimal('45'))
        response = self.client.get(reverse('property_list'))
        self.assertContains(response, 'Виктор «Эгоист»')
        self.assertContains(response, 'доля 45%')


class CustomKindTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='a@example.ru', email='a@example.ru', password='secret1')
        self.other = User.objects.create_user(username='b@example.ru', email='b@example.ru', password='secret1')
        self.client.force_login(self.user)

    def test_add_kind_is_saved_to_account(self):
        response = self.client.post(reverse('property_kind_add'), {'name': '  гараж '})
        self.assertEqual(response.json()['name'], 'Гараж')
        self.assertTrue(PropertyKind.objects.filter(owner=self.user, name='Гараж').exists())

    def test_add_existing_kind_is_reused(self):
        self.client.post(reverse('property_kind_add'), {'name': 'Гараж'})
        self.client.post(reverse('property_kind_add'), {'name': 'ГАРАЖ'})
        self.assertEqual(PropertyKind.objects.filter(owner=self.user).count(), 1)

    def test_built_in_names_are_rejected(self):
        response = self.client.post(reverse('property_kind_add'), {'name': 'дом'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('уже есть', response.json()['error'])

    def test_kinds_are_offered_only_to_their_owner(self):
        PropertyKind.objects.create(owner=self.user, name='Паркинг')
        PropertyKind.objects.create(owner=self.other, name='Чужой склад')
        page = self.client.get(reverse('property_create'))
        self.assertContains(page, 'Паркинг')
        self.assertNotContains(page, 'Чужой склад')

    def test_delete_kind_only_own_and_keeps_saved_objects(self):
        mine = PropertyKind.objects.create(owner=self.user, name='Гараж')
        foreign = PropertyKind.objects.create(owner=self.other, name='Склад')
        prop = Property.objects.create(owner=self.user, name='Г-1', kind='custom', custom_kind='Гараж')

        self.assertEqual(self.client.post(reverse('property_kind_delete', args=[foreign.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('property_kind_delete', args=[mine.pk])).status_code, 204)

        self.assertTrue(PropertyKind.objects.filter(pk=foreign.pk).exists())
        prop.refresh_from_db()
        self.assertEqual(prop.kind_label, 'Гараж')

    def test_create_object_with_custom_kind(self):
        self.client.post(reverse('property_create'), form_data(kind='custom', custom_kind='Паркинг'))
        prop = Property.objects.get()
        self.assertEqual(prop.kind_label, 'Паркинг')
        self.assertTrue(PropertyKind.objects.filter(owner=self.user, name='Паркинг').exists())

    def test_custom_kind_needs_a_name(self):
        response = self.client.post(reverse('property_create'), form_data(kind='custom', custom_kind=' '))
        self.assertContains(response, 'добавьте свой вариант')
        self.assertFalse(Property.objects.exists())

    def test_built_in_kind_clears_custom_text(self):
        self.client.post(reverse('property_create'), form_data(kind='house', custom_kind='Гараж'))
        prop = Property.objects.get()
        self.assertEqual((prop.kind_label, prop.custom_kind), ('Дом', ''))
