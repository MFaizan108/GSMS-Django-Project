from decimal import Decimal
from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction

from products.models import Category, Brand, Unit, Product, ProductPrice
from suppliers.models import Supplier
from customers.models import Customer
from settings_app.models import StoreSettings
from inventory.models import Warehouse
from inventory import services as inventory_services
from finance import services as finance_services
from finance.models import Account, LedgerEntry
from masters.models import PriceLevel

User = get_user_model()


class Command(BaseCommand):
    help = "Seed the database with a default admin user and demo data (categories, brands, units, products, one supplier, one customer)."

    def handle(self, *args, **options):
        # 1) Admin user
        if not User.objects.filter(username='admin').exists():
            User.objects.create_superuser(
                username='admin', email='admin@example.com', password='admin123', role='admin'
            )
            self.stdout.write(self.style.SUCCESS("Created admin user -> username: admin / password: admin123"))
        else:
            self.stdout.write("Admin user already exists, skipping.")

        # 2) Store settings
        settings_obj = StoreSettings.get_solo()
        if settings_obj.store_name == 'My General Store':
            settings_obj.store_name = 'Al-Falah General Store'
            settings_obj.owner_name = 'Store Owner'
            settings_obj.currency = 'PKR'
            settings_obj.save()

        # 3) Masters
        grocery, _ = Category.objects.get_or_create(name='Grocery')
        beverages, _ = Category.objects.get_or_create(name='Beverages')
        biscuits, _ = Category.objects.get_or_create(name='Biscuits')

        nestle, _ = Brand.objects.get_or_create(name='Nestle')
        national, _ = Brand.objects.get_or_create(name='National')

        piece, _ = Unit.objects.get_or_create(name='Piece', short_name='pcs')
        packet, _ = Unit.objects.get_or_create(name='Packet', short_name='pkt')
        bottle, _ = Unit.objects.get_or_create(name='Bottle', short_name='btl')

        warehouse = Warehouse.objects.filter(is_default=True).first() or Warehouse.objects.first()
        retail_level = PriceLevel.objects.filter(name='Retail').first()

        # 4) Sample products, seeded with an opening ProductBatch instead of a raw stock=
        demo_products = [
            dict(name='Nestle Milk Pack', category=grocery, brand=nestle, unit=packet,
                 purchase_price=Decimal('250'), selling_price=Decimal('280'), opening_qty=Decimal('40'),
                 minimum_stock=Decimal('10'), expiry_date=date.today() + timedelta(days=90)),
            dict(name='National Ketchup Bottle', category=grocery, brand=national, unit=bottle,
                 purchase_price=Decimal('180'), selling_price=Decimal('220'), opening_qty=Decimal('3'),
                 minimum_stock=Decimal('5'), expiry_date=date.today() + timedelta(days=10)),
            dict(name='Coca Cola 1.5L', category=beverages, brand=None, unit=bottle,
                 purchase_price=Decimal('120'), selling_price=Decimal('150'), opening_qty=Decimal('25'),
                 minimum_stock=Decimal('10'), expiry_date=date.today() + timedelta(days=180)),
            dict(name='Chocolate Biscuits Packet', category=biscuits, brand=None, unit=packet,
                 purchase_price=Decimal('40'), selling_price=Decimal('55'), opening_qty=Decimal('60'),
                 minimum_stock=Decimal('20'), expiry_date=date.today() - timedelta(days=2)),
        ]
        for p in demo_products:
            opening_qty = p.pop('opening_qty')
            selling_price = p.pop('selling_price')
            product, created = Product.objects.get_or_create(name=p['name'], defaults=p)
            if created and retail_level:
                ProductPrice.objects.get_or_create(product=product, price_level=retail_level, defaults={'price': selling_price})
            if created and warehouse:
                with transaction.atomic():
                    inventory_services.receive_stock(
                        product=product, warehouse=warehouse, quantity=opening_qty,
                        unit_cost=product.purchase_price, expiry_date=product.expiry_date,
                        batch_number='OPENING', reference='Demo seed opening stock',
                    )
                    amount = opening_qty * product.purchase_price
                    if amount:
                        inventory_account = finance_services.get_account('1200')
                        equity_account = finance_services.get_account('3000')
                        finance_services.post_transaction(
                            date=date.today(), memo=f'Opening stock: {product.name}',
                            lines=[
                                (inventory_account, LedgerEntry.EntryType.DEBIT, amount),
                                (equity_account, LedgerEntry.EntryType.CREDIT, amount),
                            ],
                        )

        # 5) Sample supplier & customer
        supplier, created = Supplier.objects.get_or_create(
            name='Ahmed Distributors', defaults=dict(company='Ahmed Traders', phone='0300-1234567')
        )
        if created:
            finance_services.get_or_create_party_account(supplier, Account.Type.LIABILITY, Account.Subtype.AP)

        customer, created = Customer.objects.get_or_create(
            name='Ali Khan', defaults=dict(phone='0333-7654321')
        )
        if created:
            finance_services.get_or_create_party_account(customer, Account.Type.ASSET, Account.Subtype.AR)

        self.stdout.write(self.style.SUCCESS("Demo data seeded successfully."))
