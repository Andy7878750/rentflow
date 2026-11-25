"""2026-11-25: every issued version is kept; the number is the day it was issued — ДДММГГ, «/1», «/2» again that day."""
from django.db import migrations, models


def date_numbers(apps, schema_editor):
    IssuedBill = apps.get_model('billing', 'IssuedBill')
    seen = {}
    for bill in IssuedBill.objects.order_by('pk'):
        base = bill.issued_on.strftime('%d%m%y')
        key = (bill.tenant_id, bill.month, base)
        n = seen.get(key, 0)
        seen[key] = n + 1
        bill.number = base if not n else f'{base}/{n}'
        bill.save(update_fields=['number'])


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0032_issued_bill_lines'),
    ]

    operations = [
        migrations.RemoveConstraint(model_name='issuedbill', name='one_bill_per_tenant_month'),
        migrations.AlterField(model_name='issuedbill', name='number', field=models.CharField(max_length=20)),
        migrations.AlterModelOptions(name='issuedbill', options={'ordering': ['-pk']}),
        migrations.RunPython(date_numbers, migrations.RunPython.noop),
    ]
