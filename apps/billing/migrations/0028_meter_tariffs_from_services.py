"""The tariff moves to the meter (2026-11-19): every meter of a metered service gets the service's tariff rows for it
(the key «m:<meter>», or its kind's / «*» before 2026-11-13) as its own history; a meter with none takes its old field."""

from datetime import date

from django.db import migrations

READY = {'electricity', 'water', 'hot_water', 'gas', 'heating'}


def copy_tariffs(apps, schema_editor):
    Receipt = apps.get_model('billing', 'Receipt')
    MeterTariff = apps.get_model('billing', 'MeterTariff')
    done = set()
    for receipt in Receipt.objects.filter(metered=True).prefetch_related('meters', 'tariffs'):
        rows = list(receipt.tariffs.all())
        for meter in receipt.meters.all():
            if meter.pk in done:
                continue
            kind_key = meter.kind if meter.kind in READY else f'custom:{meter.name}'
            for key in (f'm:{meter.pk}', kind_key, '*'):
                mine = [row for row in rows if row.key == key]
                if mine:
                    break
            for row in mine:
                MeterTariff.objects.get_or_create(meter=meter, valid_from=row.valid_from, defaults={
                    'tariff': row.tariff, 'tariff_night': row.tariff_night if meter.day_night else None})
            if not mine:
                day = meter.tariff if meter.tariff is not None else receipt.tariff
                night = meter.tariff_night if meter.tariff_night is not None else receipt.tariff_night
                if day is not None:
                    MeterTariff.objects.create(meter=meter, valid_from=date(2000, 1, 1), tariff=day,
                                               tariff_night=night if meter.day_night else None)
            done.add(meter.pk)


class Migration(migrations.Migration):
    dependencies = [('billing', '0027_service_window')]
    operations = [migrations.RunPython(copy_tariffs, migrations.RunPython.noop)]
