from django.db import migrations

ACCOUNTS = [
    ('1005', 'Cash in Safe', 'asset', 'cash'),
    ('3200', 'Owner Capital', 'equity', ''),
]


def seed_accounts(apps, schema_editor):
    Account = apps.get_model('finance', 'Account')
    for code, name, type_, subtype in ACCOUNTS:
        Account.objects.get_or_create(code=code, defaults={'name': name, 'type': type_, 'subtype': subtype})


def unseed_accounts(apps, schema_editor):
    Account = apps.get_model('finance', 'Account')
    Account.objects.filter(code__in=[c for c, *_ in ACCOUNTS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0006_seed_default_register'),
    ]

    operations = [
        migrations.RunPython(seed_accounts, unseed_accounts),
    ]
