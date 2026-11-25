"""«Счета» (2026-11-25): a bill is issued when it is given to the tenant — «PDF», «Поделиться» (both fetch the PDF) or
«Выставить»; «Посмотреть» doesn't issue. One tenant × month — one bill, the last version, the number stays."""

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
        self.assertEqual((bill.number, bill.total, bill.month), (1, Decimal('450.00'), NOV))
        self.assertEqual(bytes(bill.pdf), response.content)

    def test_issued_again_keeps_the_number_and_takes_the_place(self):
        self.pdf(self.viktor)
        self.pdf(self.vlad)
        self.cleaning.fixed_amount = Decimal('2000')
        self.cleaning.save()
        rows = dict(services.bill_rows(self.user, NOV))[self.prop]
        viktor = next(r for r in rows if r.payer.tenant.pk == self.viktor.pk)
        self.assertTrue(viktor.changed)  # «Изменился · сейчас 900 ₽»
        self.assertEqual(viktor.pay, Decimal('900.00'))
        self.pdf(self.viktor)
        bill = IssuedBill.objects.get(tenant=self.viktor)
        self.assertEqual((bill.number, bill.total), (1, Decimal('900.00')))
        self.assertEqual(IssuedBill.objects.count(), 2)

    def test_the_issued_one_is_shown_as_it_went(self):
        self.pdf(self.viktor)
        sent = bytes(IssuedBill.objects.get().pdf)
        self.cleaning.fixed_amount = Decimal('2000')
        self.cleaning.save()
        self.assertEqual(self.pdf(self.viktor, inline='1', issued='1').content, sent)

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
        self.assertContains(issued, '№ 2')
        self.assertContains(issued, 'Выставлено 2')

    def test_not_ready_is_not_issued(self):
        Receipt.objects.create(property=self.prop, name='Свет', provider='ПСК')  # by the receipt — no sum yet
        self.client.post(reverse('bill_issue'), {'month': '2026-11'})
        self.assertFalse(IssuedBill.objects.exists())
        self.assertContains(self.client.get(reverse('bill_todo'), {'month': '2026-11'}), 'не введено: Свет')
        MonthlyAmount.objects.create(receipt=Receipt.objects.get(name='Свет'), month=NOV, amount=Decimal('100'))
        self.client.post(reverse('bill_issue'), {'month': '2026-11'})
        self.assertEqual(IssuedBill.objects.count(), 2)

    def test_object_page_shows_the_issued_bill_as_it_went(self):
        self.pdf(self.viktor)
        self.cleaning.fixed_amount = Decimal('2000')
        self.cleaning.save()
        page = self.client.get(reverse('property_detail', args=[self.prop.pk]), {'month': '2026-11', 'tenant': self.viktor.pk})
        self.assertContains(page, 'Счёт № 1')
        self.assertContains(page, '450,00')  # as it went
        self.assertContains(page, 'изменился, сейчас 900,00')
        self.assertContains(page, 'Четыреста пятьдесят рублей 00 копеек')
