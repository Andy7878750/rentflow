from django.db import models


class Tenant(models.Model):
    """Someone who rents a share of a property and pays their part of the utility bills."""

    property = models.ForeignKey('properties.Property', on_delete=models.CASCADE, related_name='tenants')
    name = models.CharField('Имя или название', max_length=150)
    # Both are kept: the landlord enters one (see Property.share_unit), services fill the other.
    share_percent = models.DecimalField('Доля, %', max_digits=5, decimal_places=2, null=True, blank=True)
    area = models.DecimalField('Площадь, м²', max_digits=8, decimal_places=2, null=True, blank=True)
    phone = models.CharField('Телефон', max_length=30, blank=True)
    email = models.EmailField('Почта (для счёта)', blank=True)
    contract = models.CharField('Договор', max_length=100, blank=True)
    contract_until = models.DateField('Договор до', null=True, blank=True)

    # «Настроить счёт» (2026-11-25, docs/mockups/2026-11-25-bill-settings-layout.html, variant Б): each tenant's bill
    # is its own — a plain one (the owner's name and phone) or with requisites (both sides', VAT, «Реквизиты для оплаты»).
    class Vat(models.TextChoices):
        NONE = 'none', 'Без НДС'
        INCLUDED = 'in', 'В т. ч. НДС'
        ON_TOP = 'top', 'Сверху НДС'

    bill_requisites = models.BooleanField('Счёт с реквизитами', default=False)
    legal_name = models.CharField('Полное название', max_length=200, blank=True)
    inn = models.CharField('ИНН', max_length=12, blank=True)
    kpp = models.CharField('КПП', max_length=9, blank=True)
    legal_address = models.CharField('Адрес', max_length=250, blank=True)
    vat = models.CharField('НДС', max_length=4, choices=Vat.choices, default=Vat.NONE)
    vat_rate = models.DecimalField('Ставка НДС, %', max_digits=5, decimal_places=2, default=22)  # typed: regions differ
    due_on = models.BooleanField('Оплатить до', default=True)
    due_day = models.PositiveSmallIntegerField('Оплатить до числа', default=10)
    coef_on = models.BooleanField('Коэффициент к услугам', default=False)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return self.name
