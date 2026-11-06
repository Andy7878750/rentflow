"""«Комната» is no longer a built-in type: keep it for existing objects as the landlord's own variant."""

from django.db import migrations


def forwards(apps, schema_editor):
    Property = apps.get_model('properties', 'Property')
    PropertyKind = apps.get_model('properties', 'PropertyKind')
    for prop in Property.objects.filter(kind='room'):
        prop.kind = 'custom'
        prop.custom_kind = 'Комната'
        prop.save(update_fields=['kind', 'custom_kind'])
        PropertyKind.objects.get_or_create(owner_id=prop.owner_id, name='Комната')


def backwards(apps, schema_editor):
    Property = apps.get_model('properties', 'Property')
    Property.objects.filter(kind='custom', custom_kind='Комната').update(kind='room', custom_kind='')


class Migration(migrations.Migration):
    dependencies = [
        ('properties', '0004_custom_kinds'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
