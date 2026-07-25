from django.db import migrations

LEVELS = [
    ('Retail', True),
    ('Wholesale', False),
    ('Special', False),
]


def seed_price_levels(apps, schema_editor):
    PriceLevel = apps.get_model('masters', 'PriceLevel')
    for name, is_default in LEVELS:
        PriceLevel.objects.get_or_create(name=name, defaults={'is_default': is_default})


def unseed_price_levels(apps, schema_editor):
    PriceLevel = apps.get_model('masters', 'PriceLevel')
    PriceLevel.objects.filter(name__in=[n for n, _ in LEVELS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('masters', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_price_levels, unseed_price_levels),
    ]
