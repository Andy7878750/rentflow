"""«Счета» (2026-11-25): a bill is issued when it is given to the tenant — «PDF», «Поделиться» (both fetch the PDF) or
«Выставить»; «Посмотреть» doesn't issue. Every version is kept: № by the day it went, ДДММГГ, «/1» again that day."""

import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.properties.models import Property
from apps.tenants.models import Tenant

from . import services
from .models import IssuedBill, MonthlyAmount, Receipt

NOV = datetime.date(2026, 11, 1)


class BillsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='s@example.ru', email='s@example.ru', password='secret1')
        self.client.force_login(self.user)
        self.prop = Property.objects.create(owner=self.user, name='Счета 1', area=Decimal('60'))
        self.viktor = Tenant.objects.create(property=self.prop, name='Виктор', share_percent=Decimal('45'))
        self.vlad = Tenant.objects.create(property=self.prop, name='Владислав', share_percent=Decimal('55'))
        self.cleaning = Receipt.objects.create(property=self.prop, name='Уборка', provider='ООО «Чисто»',
                                               amount_mode=Receipt.AmountMode.FIXED, fixed_amount=Decimal('1000'))

    def pdf(self, tenant, **extra):
        url = reverse('bill_print', args=[self.prop.pk, tenant.pk])
        return self.client.get(url, {'month': '2026-11', **extra})

    def test_view_does_not_issue_download_does(self):
        self.assertEqual(self.pdf(self.viktor, inline='1').status_code, 200)
        self.assertFalse(IssuedBill.objects.exists())
        response = self.pdf(self.viktor)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        bill = IssuedBill.objects.get()
        self.assertEqual((bill.number, bill.total, bill.month), (datetime.date.today().strftime('%d%m%y'), Decimal('450.00'), NOV))
        self.assertEqual(bytes(bill.pdf), response.content)

    def test_issued_again_is_a_new_version(self):
        day = datetime.date.today().strftime('%d%m%y')
        self.pdf(self.viktor)
        self.pdf(self.viktor)  # nothing changed — the same version
        self.pdf(self.vlad)
        self.assertEqual(IssuedBill.objects.count(), 2)
        self.cleaning.fixed_amount = Decimal('2000')
        self.cleaning.save()
        self.pdf(self.viktor)
        self.assertEqual(list(IssuedBill.objects.filter(tenant=self.viktor).values_list('number', 'total')),
                         [(f'{day}/1', Decimal('900.00')), (day, Decimal('450.00'))])  # the newest first
        self.assertEqual(IssuedBill.objects.get(tenant=self.vlad).number, day)  # another tenant — the same day's №
        rows = dict(services.bill_rows(self.user, NOV))[self.prop]
        viktor = next(r for r in rows if r.payer.tenant.pk == self.viktor.pk)
        self.assertEqual([v.number for v in viktor.versions], [f'{day}/1', day])
        page = self.client.get(reverse('bill_list'), {'month': '2026-11'})
        self.assertContains(page, f'№ {day}/1')
        self.assertContains(page, f'№ {day} ·')
        self.assertNotContains(page, 'Изменился')

    def test_a_version_is_shown_as_it_went(self):
        self.pdf(self.viktor)
        first = IssuedBill.objects.get()
        self.cleaning.fixed_amount = Decimal('2000')
        self.cleaning.save()
        self.assertEqual(self.pdf(self.viktor, v=first.pk, inline='1').content, bytes(first.pdf))
        self.assertEqual(IssuedBill.objects.count(), 1, 'a version opened — nothing issued')

    def test_issue_ready_ones_and_the_lists(self):
        url = reverse('bill_issue')
        self.client.post(url, {'month': '2026-11', 'tenant': self.viktor.pk})
        self.assertEqual(list(IssuedBill.objects.values_list('tenant__name', flat=True)), ['Виктор'])
        todo = self.client.get(reverse('bill_todo'), {'month': '2026-11'})
        self.assertContains(todo, 'Владислав')
        self.assertContains(todo, 'Выставить готовые · 1')
        self.client.post(url, {'month': '2026-11'})
        self.assertEqual(IssuedBill.objects.count(), 2)
        issued = self.client.get(reverse('bill_list'), {'month': '2026-11'})
        self.assertContains(issued, 'Выставлено 2')

    def test_not_ready_is_not_issued(self):
        Receipt.objects.create(property=self.prop, name='Свет', provider='ПСК')  # by the receipt — no sum yet
        self.client.post(reverse('bill_issue'), {'month': '2026-11'})
        self.assertFalse(IssuedBill.objects.exists())
        self.assertContains(self.client.get(reverse('bill_todo'), {'month': '2026-11'}), 'не введено: Свет')
        MonthlyAmount.objects.create(receipt=Receipt.objects.get(name='Свет'), month=NOV, amount=Decimal('100'))
        self.client.post(reverse('bill_issue'), {'month': '2026-11'})
        self.assertEqual(IssuedBill.objects.count(), 2)

    def test_object_page_shows_the_bill_now(self):
        # 2026-11-25 (the user): the bill is always the count now; its № and date while it is the issued one.
        self.pdf(self.viktor)
        day = datetime.date.today()
        url = reverse('property_detail', args=[self.prop.pk])
        page = self.client.get(url, {'month': '2026-11', 'tenant': self.viktor.pk})
        self.assertContains(page, f'Счёт № {day:%d%m%y}')
        self.assertContains(page, f'выставлен {day:%d.%m.%Y}')
        self.cleaning.fixed_amount = Decimal('2000')
        self.cleaning.save()
        page = self.client.get(url, {'month': '2026-11', 'tenant': self.viktor.pk})
        self.assertContains(page, 'Девятьсот рублей 00 копеек')
        self.assertNotContains(page, 'Счёт № ')
        self.assertNotContains(page, 'изменился')
