from django.conf import settings
from django.db import models


class Property(models.Model):
    class Kind(models.TextChoices):
        APARTMENT = 'apartment', 'Квартира'
        COMMERCIAL = 'commercial', 'Нежилое помещение'
        HOUSE = 'house', 'Дом'
        ROOM = 'room', 'Комната'

    class Occupancy(models.TextChoices):
        TENANTS = 'tenants', 'Арендаторы'
        OWNER = 'owner', 'Собственник'

    class ShareUnit(models.TextChoices):
        PERCENT = 'percent', '%'
        AREA = 'area', 'м²'

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='properties')
    name = models.CharField('Короткое название', max_length=150)
    kind = models.CharField('Тип', max_length=20, choices=Kind.choices, default=Kind.APARTMENT)
    address = models.CharField('Адрес', max_length=255, blank=True)
    floor = models.CharField('Этаж', max_length=20, blank=True)
    area = models.DecimalField('Площадь, м²', max_digits=8, decimal_places=2, null=True, blank=True)

    management_company = models.CharField('УК / ТСЖ', max_length=150, blank=True)
    management_phone = models.CharField('Телефон УК / ТСЖ', max_length=30, blank=True)
    management_email = models.EmailField('Почта УК / ТСЖ', blank=True)
    cabinet_url = models.URLField('Личный кабинет', blank=True)
    cabinet_login = models.CharField('Логин', max_length=150, blank=True)
    # Only a reminder for the landlord — the real password is never stored.
    password_hint = models.CharField('Подсказка к паролю', max_length=150, blank=True)

    occupancy = models.CharField(max_length=10, choices=Occupancy.choices, default=Occupancy.TENANTS)
    share_unit = models.CharField(max_length=10, choices=ShareUnit.choices, default=ShareUnit.PERCENT)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return self.name

    @property
    def phone_href(self):
        """tel: link value — digits and a leading plus only."""
        digits = ''.join(ch for ch in self.management_phone if ch.isdigit())
        return f'+{digits}' if digits else ''

    @property
    def is_owner_used(self):
        return self.occupancy == self.Occupancy.OWNER
