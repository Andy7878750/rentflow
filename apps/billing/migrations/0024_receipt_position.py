from django.db import migrations, models


def number_receipts(apps, schema_editor):
    """The services of each object keep the order they had (by creation): 1, 2, 3…"""
    Receipt = apps.get_model('billing', 'Receipt')
    counters = {}
    for receipt in Receipt.objects.order_by('property_id', 'created_at', 'id'):
        counters[receipt.property_id] = counters.get(receipt.property_id, 0) + 1
        receipt.position = counters[receipt.property_id]
        receipt.save(update_fields=['position'])


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0023_tile_per_property'),
    ]

    operations = [
        migrations.AddField(
            model_name='receipt',
            name='position',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AlterModelOptions(
            name='receipt',
            options={'ordering': ['position', 'created_at', 'id']},
        ),
        migrations.RunPython(number_receipts, migrations.RunPython.noop),
    ]
