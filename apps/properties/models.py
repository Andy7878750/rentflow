from django.conf import settings
from django.db import models


class Property(models.Model):
    class Kind(models.TextChoices):
        APARTMENT = 'apartment', 'Квартира'
        COMMERCIAL = 'commercial', 'Нежилое помещение'
        HOUSE = 'house', 'Дом'
        ROOM = 'room', 'Комната'

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='properties')
    name = models.CharField(max_length=150)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.APARTMENT)
    address = models.CharField(max_length=255)
    management_company = models.CharField('УК', max_length=150, blank=True)
    management_phone = models.CharField('Телефон УК', max_length=30, blank=True)
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
