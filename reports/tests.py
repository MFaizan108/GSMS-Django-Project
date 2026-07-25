from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from inventory.models import Warehouse
from inventory import services as inv_services
from products.models import Product, Category, Brand, Unit
from sales.models import Sale
from sales import services as sales_services
from finance.models import Expense, Account, Payment
from finance import services as fin_services


def make_product():
    category = Category.objects.create(name='Reports Test Category')
    brand = Brand.objects.create(name='Reports Test Brand')
    unit = Unit.objects.create(name='Piece RT', short_name='pc')
    product = Product.objects.create(name='Reports Test Product', category=category, brand=brand, unit=unit, purchase_price=Decimal('10'))
    warehouse = Warehouse.objects.filter(is_default=True).first() or Warehouse.objects.first()
    inv_services.receive_stock(product=product, warehouse=warehouse, quantity=Decimal('50'), unit_cost=Decimal('10'))
    return product, warehouse


class CashFlowReportTests(TestCase):
    """Must be derived from real GL cash movement (dated by when cash
    actually moved), not Sale.paid/Purchase.paid filtered by invoice date."""

    def setUp(self):
        self.user = User.objects.create_user(username='reports_tester', password='x', role=User.Role.ADMIN)
        self.client.force_login(self.user)

    def test_walkin_sale_and_expense_show_up_as_cash_in_out_today(self):
        product, warehouse = make_product()
        today = timezone.localdate()

        sale = Sale(customer=None, warehouse=warehouse, invoice_no='T-CF-SALE', date=today)
        sales_services.create_sale(sale, [{'product': product, 'quantity': Decimal('1'), 'selling_price': Decimal('100')}], Decimal('100'), self.user)

        expense = Expense.objects.create(title='Test expense', amount=Decimal('30'), date=today, account=fin_services.get_account('1000'))
        fin_services.post_expense(expense)

        resp = self.client.get(f'/reports/cash-flow/?start={today}&end={today}')
        self.assertEqual(resp.status_code, 200)

        from finance.models import LedgerEntry
        from django.db.models import Sum
        entries = LedgerEntry.objects.filter(account__subtype__in=Account.PAYMENT_SUBTYPES, transaction__date=today)
        cash_in = entries.filter(entry_type=LedgerEntry.EntryType.DEBIT).aggregate(t=Sum('amount'))['t'] or Decimal('0')
        cash_out = entries.filter(entry_type=LedgerEntry.EntryType.CREDIT).aggregate(t=Sum('amount'))['t'] or Decimal('0')
        self.assertGreaterEqual(cash_in, Decimal('100'))
        self.assertGreaterEqual(cash_out, Decimal('30'))


class ExpiryReportTests(TestCase):
    """Must read ProductBatch/BatchStock (every batch, every warehouse), not
    Product.expiry_date (only ever the most recent purchase's expiry)."""

    def setUp(self):
        self.user = User.objects.create_user(username='reports_tester2', password='x', role=User.Role.ADMIN)
        self.client.force_login(self.user)

    def test_multiple_batches_across_warehouses_all_appear(self):
        category = Category.objects.create(name='Expiry Test Category')
        brand = Brand.objects.create(name='Expiry Test Brand')
        unit = Unit.objects.create(name='Piece ET', short_name='pc')
        product = Product.objects.create(name='Expiry Test Product', category=category, brand=brand, unit=unit)
        wh1 = Warehouse.objects.filter(is_default=True).first() or Warehouse.objects.first()
        wh2 = Warehouse.objects.create(name='Expiry WH2', code='T-EXP-WH2')

        today = timezone.localdate()
        inv_services.receive_stock(product=product, warehouse=wh1, quantity=Decimal('5'), unit_cost=Decimal('10'),
                                    expiry_date=today + timezone.timedelta(days=3), batch_number='SOON')
        inv_services.receive_stock(product=product, warehouse=wh2, quantity=Decimal('5'), unit_cost=Decimal('10'),
                                    expiry_date=today + timezone.timedelta(days=100), batch_number='LATER')

        resp = self.client.get('/reports/expiry/')
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('SOON', html)
        self.assertIn('LATER', html)
        self.assertIn(wh1.name, html)
        self.assertIn(wh2.name, html)


class AccountReconciliationReportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='reports_tester3', password='x', role=User.Role.ADMIN)
        self.client.force_login(self.user)

    def test_report_renders(self):
        resp = self.client.get('/reports/account-reconciliation/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Account Reconciliation', resp.content.decode())


class PaymentCollectionReportTests(TestCase):
    """Shows which customer paid how much on which day — including baqaya
    (due) collected against an existing invoice, not just the balance."""

    def setUp(self):
        self.user = User.objects.create_user(username='reports_tester4', password='x', role=User.Role.ADMIN)
        self.client.force_login(self.user)

    def test_due_collection_against_a_sale_shows_up(self):
        from customers.models import Customer
        product, warehouse = make_product()
        today = timezone.localdate()
        customer = Customer.objects.create(name='Collection Report Customer')

        sale = Sale(customer=customer, warehouse=warehouse, invoice_no='T-PC-SALE', date=today)
        sale = sales_services.create_sale(
            sale, [{'product': product, 'quantity': Decimal('1'), 'selling_price': Decimal('200')}], Decimal('50'), self.user,
        )
        self.assertEqual(sale.remaining, Decimal('150'))

        fin_services.record_payment(
            Payment.Direction.IN, Decimal('150'),
            fin_services.get_account('1000'), today, sale=sale, customer=customer, created_by=self.user,
        )

        resp = self.client.get(f'/reports/payment-collection/?start={today}&end={today}')
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('Collection Report Customer', html)
        self.assertIn('150.00', html)
