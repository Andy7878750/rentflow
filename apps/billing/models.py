import builtins

from django.conf import settings
from django.db import models


class Receipt(models.Model):
    """A bill that comes for a property every month (or a fixed charge), set up once.

    How it is split between tenants is chosen here; monthly amounts and readings come later.
    """

    class Kind(models.TextChoices):
        # The order is the order of the template tiles in «Новая услуга».
        ELECTRICITY = 'electricity', 'Электричество'
        WATER = 'water', 'Вода холодная'
        HOT_WATER = 'hot_water', 'Вода горячая'
        HOT_WATER_HEATING = 'hot_water_heating', 'Вода горячая / подогрев'
        SEWAGE = 'sewage', 'Водоотведение'
        HEATING = 'heating', 'Отопление'
        GAS = 'gas', 'Газ'
        MANAGEMENT = 'management', 'Содержание и ремонт'
        CAPITAL_REPAIR = 'capital_repair', 'Капитальный ремонт'
        GARBAGE = 'garbage', 'Вывоз мусора'
        INTERNET = 'internet', 'Интернет'
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

    class Layout(models.TextChoices):
        COMMON = 'common', 'Общий на объект'
        TENANTS = 'tenants', 'У каждого свой'
        BOTH = 'both', 'Общий + у каждого свой'

    metered = models.BooleanField('Есть счётчик', default=False)
    unit = models.CharField('Единица', max_length=10, blank=True)  # кВт·ч, м³ — for metered receipts
    # Single-rate meters use `tariff`; day / night ones use `tariff` for the day and `tariff_night`.
    zones = models.PositiveSmallIntegerField('Тарифы', default=1, choices=[(1, 'Однотарифный'), (2, 'День / ночь')])
    tariff = models.DecimalField('Тариф', max_digits=10, decimal_places=4, null=True, blank=True)
    tariff_night = models.DecimalField('Тариф ночь', max_digits=10, decimal_places=4, null=True, blank=True)

    class InputMode(models.TextChoices):
        READINGS = 'readings', 'Показания'  # «было / стало» each month, from the starting reading
        USAGE = 'usage', 'Расход'           # just how much was used this month

    input_mode = models.CharField('Каждый месяц вводим', max_length=10, choices=InputMode.choices,
                                  default=InputMode.READINGS)
    # Which meters there are: one common, one per tenant, or a common one for the supplier plus
    # the tenants' own (the difference stays with the owner for now).
    layout = models.CharField('Какие счётчики', max_length=10, choices=Layout.choices, default=Layout.COMMON)

    split = models.CharField('Как делить', max_length=10, choices=Split.choices, default=Split.SHARES)
    amount_mode = models.CharField('Сумма', max_length=10, choices=AmountMode.choices, default=AmountMode.MONTHLY)
    fixed_amount = models.DecimalField('Сумма в месяц', max_digits=12, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, default=settings.CURRENCY)
    # The object's meters whose readings drive this service. One meter can serve several services
    # (cold water and sewage, say).
    meters = models.ManyToManyField('Meter', related_name='receipts', blank=True)
    # «Кто платит» → tenants switched off for this service (internet only for one of them, say).
    # Their part stays with the owner; «поровну» divides between those who pay.
    excluded = models.ManyToManyField('tenants.Tenant', related_name='excluded_receipts', blank=True)
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
    """A real meter on the object: a tenant's own one, or a common one (tenant is empty).

    It belongs to the object, not to a service: services link to it (Receipt.meters), so the
    same meter can drive several of them and keeps its readings when a service changes.
    """

    property = models.ForeignKey('properties.Property', on_delete=models.CASCADE, related_name='meters')
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE, null=True, blank=True, related_name='meters')
    # What it measures: a ready-made kind, or «custom» with the landlord's own name.
    kind = models.CharField(max_length=20, choices=Receipt.Kind.choices, blank=True)
    name = models.CharField(max_length=100)  # «Вода холодная», «Электричество» or the own name
    serial = models.CharField('Номер счётчика', max_length=50, blank=True)
    # The meter's own tariff and unit; empty — the service's («Сколько стоит»).
    tariff = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    tariff_night = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    unit = models.CharField(max_length=20, blank=True)
    # What it showed when it was set up: «было» of its first month.
    initial = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    initial_night = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'{self.name} · {self.who}'

    @builtins.property  # «property» here is the object field
    def who(self):
        """Whose meter it is: the tenant, or the object itself."""
        return self.tenant.name if self.tenant_id else 'Объект (общий)'


class MonthlyAmount(models.Model):
    """What a receipt says for one month: the sum to pay, or (for metered ones) the tariff."""

    receipt = models.ForeignKey(Receipt, on_delete=models.CASCADE, related_name='monthly_amounts')
    month = models.DateField()  # always the 1st of the month
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    # The tariff a past month was billed at, kept when the service's tariff changes.
    tariff = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    tariff_night = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['receipt', 'month'], name='unique_amount_per_receipt_month')]


class Reading(models.Model):
    """A meter's readings for one month: what it showed before and now."""

    meter = models.ForeignKey(Meter, on_delete=models.CASCADE, related_name='readings')
    month = models.DateField()  # always the 1st of the month
    previous = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    current = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    # Day / night meters: the fields above are the day, these the night.
    previous_night = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    current_night = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    # Services that take the month's usage instead of readings («Расход»).
    usage = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    usage_night = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)

    class Meta:
        ordering = ['month']
        constraints = [models.UniqueConstraint(fields=['meter', 'month'], name='unique_reading_per_meter_month')]

    @builtins.property
    def consumption(self):
        if self.previous is None or self.current is None:
            return None
        return self.current - self.previous

    @builtins.property
    def consumption_night(self):
        if self.previous_night is None or self.current_night is None:
            return None
        return self.current_night - self.previous_night
