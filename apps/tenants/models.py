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

    class Meta:
        ordering = ['id']

    def __str__(self):
        return self.name
