from django.db import migrations


def forwards(apps, schema_editor):
    """Each existing meter: belongs to its service's object, measures what the service is, and is linked back."""
    Meter = apps.get_model('billing', 'Meter')
    for meter in Meter.objects.select_related('receipt'):
        meter.property_id = meter.receipt.property_id
        meter.kind = meter.receipt.kind
        meter.save(update_fields=['property', 'kind'])
        meter.receipt.meters.add(meter)


def backwards(apps, schema_editor):
    Meter = apps.get_model('billing', 'Meter')
    for meter in Meter.objects.all():
        receipt = meter.receipts.first()
        if receipt is None:
            meter.delete()
        else:
            meter.receipt = receipt
            meter.save(update_fields=['receipt'])


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0006_meter_property'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
