from django.db import migrations

ACCOUNTS = [
    ('1000', 'Cash in Hand', 'asset', 'cash'),
    ('1010', 'Bank Account', 'asset', 'bank'),
    ('1020', 'JazzCash', 'asset', 'mobile_wallet'),
    ('1030', 'Easypaisa', 'asset', 'mobile_wallet'),
    ('1040', 'Other Receipts', 'asset', 'other'),
    ('1100', 'Accounts Receivable', 'asset', 'ar'),
    ('1200', 'Inventory', 'asset', 'inventory'),
    ('2000', 'Accounts Payable', 'liability', 'ap'),
    ('3000', 'Opening Balance Equity', 'equity', ''),
    ('4000', 'Sales Revenue', 'income', ''),
    ('4100', 'Other Income', 'income', ''),
    ('4200', 'Inventory Adjustment Income', 'income', ''),
    ('5000', 'Cost of Goods Sold', 'expense', ''),
    ('5100', 'Operating Expenses', 'expense', ''),
    ('5200', 'Inventory Shrinkage Expense', 'expense', ''),
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
        ('finance', '0002_initial'),
    ]

    operations = [
        migrations.RunPython(seed_accounts, unseed_accounts),
    ]
