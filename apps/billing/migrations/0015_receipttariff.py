import datetime

import django.db.models.deletion
from django.db import migrations, models

# Months before a service's first tariff change: its tariff applies «from always».
SINCE_ALWAYS = datetime.date(2000, 1, 1)
METER_KINDS = {'electricity', 'water', 'hot_water', 'gas', 'heating'}


def tariff_key(receipt, meter):
    if receipt.kind == 'sewage':
        return '*'
    return meter.kind if meter.kind in METER_KINDS else f'custom:{meter.name}'


def tariffs_to_services(apps, schema_editor):
    """The tariff moves from the meters (and the service) to the service, one per kind of its meters.

    A service whose past months keep an old tariff (MonthlyAmount.tariff) gets its current one from
    the month after the last of them, so those months stay as they were billed.
    """
    Receipt = apps.get_model('billing', 'Receipt')
    ReceiptTariff = apps.get_model('billing', 'ReceiptTariff')
    for receipt in Receipt.objects.filter(metered=True):
        last = (
            receipt.monthly_amounts.exclude(tariff=None).order_by('-month').values_list('month', flat=True).first()
        )
        if last:
            valid_from = (last.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
        else:
            valid_from = SINCE_ALWAYS
        found = {}
        for meter in receipt.meters.order_by('id'):
            key = tariff_key(receipt, meter)
            day = meter.tariff if meter.tariff is not None else receipt.tariff
            night = meter.tariff_night if meter.tariff is not None else receipt.tariff_night
            if key not in found and day is not None:
                found[key] = (day, night)
        for key, (day, night) in found.items():
            ReceiptTariff.objects.create(receipt=receipt, key=key, valid_from=valid_from, tariff=day, tariff_night=night)


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0014_meter_vacant_day_night'),
    ]

    operations = [
        migrations.CreateModel(
            name='ReceiptTariff',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(max_length=120)),
                ('valid_from', models.DateField()),
                ('tariff', models.DecimalField(decimal_places=4, max_digits=10)),
                ('tariff_night', models.DecimalField(blank=True, decimal_places=4, max_digits=10, null=True)),
                ('receipt', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tariffs', to='billing.receipt')),
            ],
            options={
                'ordering': ['receipt', 'key', 'valid_from'],
                'constraints': [models.UniqueConstraint(fields=('receipt', 'key', 'valid_from'), name='unique_tariff_per_month')],
            },
        ),
        migrations.RunPython(tariffs_to_services, migrations.RunPython.noop),
    ]
