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
        # A sum from the receipt divided in proportion to the chosen meters' usage (one bill for two meters, 2026-11-16).
        USAGE = 'usage', 'По расходу'
        OWNER = 'owner', 'Плачу сам'

    class AmountMode(models.TextChoices):
        MONTHLY = 'monthly', 'Каждый месяц разная'
        FIXED = 'fixed', 'Постоянная'
        # A tariff × the object's area or × the number of people (garbage, capital repair; 2026-11-16).
        RATE = 'rate', 'По площади / на человека'
        # The owner's own formula of numbers, meters and signs (formula.py; 2026-11-16).
        FORMULA = 'formula', 'Своя формула'

    class RateBase(models.TextChoices):
        AREA = 'area', 'за м²'
        PERSON = 'person', 'за человека'

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
    # «По расходу» with a day / night meter: a night kWh weighs this much of a day one (0,6 — night is cheaper).
    # Empty — the same as a day one (day + night).
    night_weight = models.DecimalField('Ночь к дню', max_digits=5, decimal_places=3, null=True, blank=True)
    amount_mode = models.CharField('Сумма', max_length=10, choices=AmountMode.choices, default=AmountMode.MONTHLY)
    fixed_amount = models.DecimalField('Сумма в месяц', max_digits=12, decimal_places=2, null=True, blank=True)
    # «По площади»: the price per m² (of the object's area) or per person, and how many people — typed in the service
    # itself, not kept on the tenants. Kept with history in ReceiptTariff (key «rate:area» / «rate:person»).
    rate_base = models.CharField('За что', max_length=10, choices=RateBase.choices, default=RateBase.AREA)
    rate = models.DecimalField('Тариф', max_digits=10, decimal_places=4, null=True, blank=True)
    persons = models.PositiveSmallIntegerField('Человек', null=True, blank=True)
    currency = models.CharField(max_length=3, default=settings.CURRENCY)
    # «Своя формула»: the blocks in order — {"t": "num", "id": <FormulaNumber>}, {"t": "meter", "key": <kind or
    # «custom:<name>»>, "meters": [<Meter ids>], "join": "each" | "sum"}, {"t": "op", "op": "+" | "−" | "×" | "÷" | "(" | ")"}.
    formula = models.JSONField(default=list, blank=True)
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
    # The order of the service cards on the object page (the owner drags them); a new one goes last.
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['position', 'created_at', 'id']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.pk is None and not self.position:
            last = Receipt.objects.filter(property_id=self.property_id).aggregate(models.Max('position'))['position__max']
            self.position = (last or 0) + 1
        super().save(*args, **kwargs)

    @builtins.property  # plain `property` is the ForeignKey field above
    def currency_symbol(self):
        return {'RUB': '₽', 'EUR': '€'}.get(self.currency, self.currency)


class Meter(models.Model):
    """A real meter on the object: a tenant's own one, or a common one (tenant is empty).

    It belongs to the object, not to a service: services link to it (Receipt.meters), so the
    same meter can drive several of them and keeps its readings when a service changes.
    """

    property = models.ForeignKey('properties.Property', on_delete=models.CASCADE, related_name='meters')
    # Who pays by it now. Empty — a common meter, or a free one (see `vacant`). A tenant who moves out
    # leaves the meter on the object: it is the premises', not the tenant's.
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.SET_NULL, null=True, blank=True, related_name='meters')
    # «Свободен»: its tenant moved out — the owner pays by it until a new tenant takes it.
    vacant = models.BooleanField(default=False)
    # Two zones: day and night readings (initial / initial_night, Reading.*_night).
    day_night = models.BooleanField(default=False)
    # What is typed every month (2026-11-16, per meter): «Было / стало» or «Расход». Empty — as its service says.
    input_mode = models.CharField(max_length=10, choices=Receipt.InputMode.choices, blank=True)
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
        """Whose meter it is: the tenant, a free one, or the object itself."""
        if self.tenant_id:
            return self.tenant.name
        return 'Свободен' if self.vacant else 'Объект (общий)'


class ReceiptTariff(models.Model):
    """A service's tariff for one kind of its meters, from a month on.

    A service may gather meters of several kinds (light day / night, hot and cold water), each kind
    with its own price; sewage has one price for all its meters (key «*»). A new price is a new row
    from the current month, so earlier months and issued bills keep the old one.
    """

    receipt = models.ForeignKey(Receipt, on_delete=models.CASCADE, related_name='tariffs')
    # Which meters: their kind («electricity», «water»…), «custom:<name>» for an own kind, «*» — all of them.
    key = models.CharField(max_length=120)
    valid_from = models.DateField()  # the 1st of the month it applies from
    tariff = models.DecimalField(max_digits=10, decimal_places=4)
    tariff_night = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    # «По площади · за человека»: how many people from this month (the tariff is in `tariff`).
    quantity = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        ordering = ['receipt', 'key', 'valid_from']
        constraints = [models.UniqueConstraint(fields=['receipt', 'key', 'valid_from'], name='unique_tariff_per_month')]

    def __str__(self):
        return f'{self.receipt} · {self.key} · с {self.valid_from:%m.%Y}'


class ServiceTemplate(models.Model):
    """The owner's own tile in «Новая услуга»: a «Своя» service saved «как плашка».

    Keeps only what does not depend on an object: the name, the supplier, how it is charged and split.
    Meters and tariffs are each object's own — picked in the window every time.
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='service_templates')
    # The object it was saved on: the tile shows only there; other objects keep the standard tiles (2026-11-16).
    property = models.ForeignKey('properties.Property', on_delete=models.CASCADE, related_name='service_templates',
                                 null=True, blank=True)
    name = models.CharField(max_length=100)
    provider = models.CharField(max_length=150, blank=True)
    metered = models.BooleanField(default=False)
    amount_mode = models.CharField(max_length=10, choices=Receipt.AmountMode.choices, default=Receipt.AmountMode.MONTHLY)
    fixed_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    split = models.CharField(max_length=10, choices=Receipt.Split.choices, default=Receipt.Split.SHARES)
    input_mode = models.CharField(max_length=10, choices=Receipt.InputMode.choices, default=Receipt.InputMode.READINGS)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']
        constraints = [models.UniqueConstraint(fields=['property', 'name'], name='unique_template_name_per_property')]

    def __str__(self):
        return self.name


class FormulaNumber(models.Model):
    """A number of a service's own formula: «Каждый месяц» (typed on the object page, FormulaValue) or
    «Тариф / норматив» (set once; its history — ReceiptTariff with the key «num:<id>»).

    Its unit: «₽ за Гкал» — unit «₽», per «Гкал»; the formula checks the result comes out in rubles.
    """

    receipt = models.ForeignKey(Receipt, on_delete=models.CASCADE, related_name='numbers')
    label = models.CharField(max_length=60)
    monthly = models.BooleanField(default=False)
    unit = models.CharField(max_length=12, blank=True)
    per = models.CharField(max_length=12, blank=True)
    value = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)  # «Тариф / норматив» now
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['position', 'id']

    def __str__(self):
        return self.label


class FormulaValue(models.Model):
    """What a «Каждый месяц» number of a formula is in one month (typed on the object page)."""

    number = models.ForeignKey(FormulaNumber, on_delete=models.CASCADE, related_name='values')
    month = models.DateField()
    value = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)

    class Meta:
        ordering = ['month']
        constraints = [models.UniqueConstraint(fields=['number', 'month'], name='unique_formula_value_per_month')]


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
