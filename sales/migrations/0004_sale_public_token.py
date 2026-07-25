import uuid

from django.db import migrations, models


def backfill_public_tokens(apps, schema_editor):
    Sale = apps.get_model('sales', 'Sale')
    for sale in Sale.objects.filter(public_token__isnull=True):
        sale.public_token = uuid.uuid4()
        sale.save(update_fields=['public_token'])


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0003_sale_register'),
    ]

    operations = [
        migrations.AddField(
            model_name='sale',
            name='public_token',
            field=models.UUIDField(null=True, editable=False),
        ),
        migrations.RunPython(backfill_public_tokens, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='sale',
            name='public_token',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
