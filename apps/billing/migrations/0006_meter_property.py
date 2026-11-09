from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    """Meters move from a service to the object: step 1, new columns next to the old link."""

    dependencies = [
        ('billing', '0005_alter_receipt_kind'),
        ('properties', '0005_room_to_custom_kind'),
    ]

    operations = [
        migrations.AlterField(
            model_name='meter',
            name='receipt',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='old_meters', to='billing.receipt'),
        ),
        migrations.AddField(
            model_name='meter',
            name='property',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='meters', to='properties.property'),
        ),
        migrations.AddField(
            model_name='meter',
            name='kind',
            field=models.CharField(blank=True, choices=[('electricity', 'Электричество'), ('water', 'Вода холодная'), ('hot_water', 'Вода горячая'), ('hot_water_heating', 'Вода горячая / подогрев'), ('sewage', 'Водоотведение'), ('heating', 'Отопление'), ('gas', 'Газ'), ('management', 'Содержание и ремонт'), ('capital_repair', 'Капитальный ремонт'), ('garbage', 'Вывоз мусора'), ('internet', 'Интернет'), ('custom', 'Своя услуга')], max_length=20),
        ),
        migrations.AddField(
            model_name='meter',
            name='serial',
            field=models.CharField(blank=True, max_length=50, verbose_name='Номер счётчика'),
        ),
        migrations.AddField(
            model_name='receipt',
            name='meters',
            field=models.ManyToManyField(blank=True, related_name='receipts', to='billing.meter'),
        ),
    ]
