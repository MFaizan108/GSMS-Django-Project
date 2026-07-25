from django.db import migrations


def seed_warehouse(apps, schema_editor):
    Warehouse = apps.get_model('inventory', 'Warehouse')
    Warehouse.objects.get_or_create(code='MAIN', defaults={'name': 'Main Store', 'is_default': True})


def unseed_warehouse(apps, schema_editor):
    Warehouse = apps.get_model('inventory', 'Warehouse')
    Warehouse.objects.filter(code='MAIN').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0002_initial'),
    ]

    operations = [
        migrations.RunPython(seed_warehouse, unseed_warehouse),
    ]
