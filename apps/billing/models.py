import builtins

from django.conf import settings
from django.db import models


class Receipt(models.Model):
    """A bill that comes for a property every month (or a fixed charge), set up once.

    How it is split between tenants is chosen here; monthly amounts and readings come later.
    """

    class Kind(models.TextChoices):
        MANAGEMENT = 'management', 'УК / ЖКУ'
        ELECTRICITY = 'electricity', 'Свет'
        WATER = 'water', 'Вода'
        GAS = 'gas', 'Газ'
        INTERNET = 'internet', 'Интернет'
        CAPITAL_REPAIR = 'capital_repair', 'Капремонт'
        GARBAGE = 'garbage', 'Вывоз мусора'
        CUSTOM = 'custom', 'Своя услуга'

    class Split(models.TextChoices):
        SHARES = 'shares', 'По долям'
        EQUAL = 'equal', 'Поровну'
        AREA = 'area', 'По м²'
        METERS = 'meters', 'По показаниям'
        OWNER = 'owner', 'Плачу сам'

    class AmountMode(models.TextChoices):
        MONTHLY = 'monthly', 'Каждый месяц разная'
        FIXED = 'fixed', 'Постоянная'

    property = models.ForeignKey('properties.Property', on_delete=models.CASCADE, related_name='receipts')
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.CUSTOM)
    name = models.CharField('Название', max_length=100)
    provider = models.CharField('Кому платим', max_length=150, blank=True)

    metered = models.BooleanField('Есть счётчик', default=False)
    unit = models.CharField('Единица', max_length=10, blank=True)  # кВт·ч, м³ — for metered receipts
    tariff = models.DecimalField('Тариф', max_digits=10, decimal_places=4, null=True, blank=True)

    split = models.CharField('Как делить', max_length=10, choices=Split.choices, default=Split.SHARES)
    amount_mode = models.CharField('Сумма', max_length=10, choices=AmountMode.choices, default=AmountMode.MONTHLY)
    fixed_amount = models.DecimalField('Сумма в месяц', max_digits=12, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, default=settings.CURRENCY)
    # Multiplies what tenants are billed: VAT (1,2) or the landlord's own markup. The owner's
    # remainder is counted without it.
    coefficient = models.DecimalField('Коэффициент', max_digits=6, decimal_places=4, default=1)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']

    def __str__(self):
        return self.name

    @builtins.property  # plain `property` is the ForeignKey field above
    def currency_symbol(self):
        return {'RUB': '₽', 'EUR': '€'}.get(self.currency, self.currency)


class Meter(models.Model):
    """A meter whose readings drive a receipt: one per tenant, or one common meter (tenant is empty)."""

    receipt = models.ForeignKey(Receipt, on_delete=models.CASCADE, related_name='meters')
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE, null=True, blank=True, related_name='meters')
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return self.name


class MonthlyAmount(models.Model):
    """What a receipt says for one month: the sum to pay, or (for metered ones) the tariff."""

    receipt = models.ForeignKey(Receipt, on_delete=models.CASCADE, related_name='monthly_amounts')
    month = models.DateField()  # always the 1st of the month
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    tariff = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['receipt', 'month'], name='unique_amount_per_receipt_month')]


class Reading(models.Model):
    """A meter's readings for one month: what it showed before and now."""

    meter = models.ForeignKey(Meter, on_delete=models.CASCADE, related_name='readings')
    month = models.DateField()  # always the 1st of the month
    previous = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    current = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)

    class Meta:
        ordering = ['month']
        constraints = [models.UniqueConstraint(fields=['meter', 'month'], name='unique_reading_per_meter_month')]

    @builtins.property
    def consumption(self):
        if self.previous is None or self.current is None:
            return None
        return self.current - self.previous
