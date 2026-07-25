from django.db import migrations


def seed_register(apps, schema_editor):
    Account = apps.get_model('finance', 'Account')
    CashRegister = apps.get_model('finance', 'CashRegister')
    Warehouse = apps.get_model('inventory', 'Warehouse')

    cash_account = Account.objects.filter(code='1000').first()
    if not cash_account:
        return
    warehouse = Warehouse.objects.filter(is_default=True).first()
    CashRegister.objects.get_or_create(
        code='MAIN', defaults={'name': 'Main Register', 'warehouse': warehouse, 'linked_account': cash_account},
    )


def unseed_register(apps, schema_editor):
    CashRegister = apps.get_model('finance', 'CashRegister')
    CashRegister.objects.filter(code='MAIN').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0005_cashregister_cashtransaction'),
        ('inventory', '0003_seed_default_warehouse'),
    ]

    operations = [
        migrations.RunPython(seed_register, unseed_register),
    ]
