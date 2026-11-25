from django.conf import settings
from django.db import models


class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    full_name = models.CharField(max_length=150)
    privacy_consent_at = models.DateTimeField()

    def __str__(self):
        return self.full_name


class Requisites(models.Model):
    """The landlord's own requisites for bills «с реквизитами» (2026-11-25): typed once, go to every such bill —
    the head «Арендодатель» and «Реквизиты для оплаты». Empty — the bill has only the name."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='requisites')
    legal_name = models.CharField('Полное название', max_length=200, blank=True)  # «ИП Иванов Андрей Петрович»
    inn = models.CharField('ИНН', max_length=12, blank=True)
    ogrn = models.CharField('ОГРН / ОГРНИП', max_length=15, blank=True)
    kpp = models.CharField('КПП', max_length=9, blank=True)
    address = models.CharField('Адрес', max_length=250, blank=True)
    phone = models.CharField('Телефон', max_length=30, blank=True)
    email = models.EmailField('Почта', blank=True)
    account = models.CharField('Расчётный счёт', max_length=20, blank=True)
    bank = models.CharField('Банк', max_length=200, blank=True)
    bik = models.CharField('БИК', max_length=9, blank=True)
    corr_account = models.CharField('Корр. счёт', max_length=20, blank=True)

    @property
    def has_bank(self):
        return bool(self.account and self.bank and self.bik)
