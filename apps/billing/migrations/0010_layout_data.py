from django.db import migrations


def forwards(apps, schema_editor):
    """Services split by readings had one meter per tenant: that is the «У каждого свой» layout."""
    Receipt = apps.get_model('billing', 'Receipt')
    Receipt.objects.filter(metered=True, split='meters').update(layout='tenants')


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [('billing', '0009_meter_zones_layout')]
    operations = [migrations.RunPython(forwards, backwards)]
