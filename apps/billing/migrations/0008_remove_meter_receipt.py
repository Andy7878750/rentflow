from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    """Meters move from a service to the object: step 3, drop the old link."""

    dependencies = [
        ('billing', '0007_meter_property_data'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='meter',
            name='receipt',
        ),
        migrations.AlterField(
            model_name='meter',
            name='property',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='meters', to='properties.property'),
        ),
    ]
