from django.db import migrations


def release(apps, schema_editor):
    """A meter no service counts by is the premises' common one (2026-11-16): take the tenants off such meters."""
    Meter = apps.get_model('billing', 'Meter')
    Meter.objects.filter(receipts__isnull=True).exclude(tenant=None, vacant=False).update(tenant=None, vacant=False)


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0017_split_by_usage'),
    ]

    operations = [
        migrations.RunPython(release, migrations.RunPython.noop),
    ]
