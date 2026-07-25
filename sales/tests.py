from decimal import Decimal

from django.test import TestCase
from django.db.models import Sum

from customers.models import Customer
from inventory.models import Warehouse
from inventory import services as inv_services
from products.models import Product, Category, Brand, Unit
from finance.models import Payment
from .models import Sale
from . import services as sales_services
from .views import _whatsapp_number


def make_product():
    category = Category.objects.create(name='Sales Test Category')
    brand = Brand.objects.create(name='Sales Test Brand')
    unit = Unit.objects.create(name='Piece ST', short_name='pc')
    product = Product.objects.create(name='Sales Test Product', category=category, brand=brand, unit=unit, purchase_price=Decimal('10'))
    warehouse = Warehouse.objects.filter(is_default=True).first() or Warehouse.objects.first()
    inv_services.receive_stock(product=product, warehouse=warehouse, quantity=Decimal('100'), unit_cost=Decimal('10'))
    return product, warehouse


class SaleOverpaymentTests(TestCase):
    """Cash tendered beyond a customer sale's invoice total is handed back
    as change on the spot — same as a walk-in sale — so it must NOT linger
    as an on-account advance/credit on the customer's ledger."""

    def test_credit_sale_overpayment_is_given_as_change_not_customer_credit(self):
        product, warehouse = make_product()
        customer = Customer.objects.create(name='Sales Overpay Customer')
        sale = Sale(customer=customer, warehouse=warehouse, invoice_no='T-SALE-OVERPAY', date='2026-07-25')
        sale = sales_services.create_sale(
            sale, [{'product': product, 'quantity': Decimal('1'), 'selling_price': Decimal('100')}], Decimal('150'), None,
        )
        sale.refresh_from_db()

        self.assertEqual(sale.total, Decimal('100'))
        self.assertEqual(sale.paid, Decimal('100'), 'invoice-tied payment should be capped at the invoice total')
        self.assertEqual(sale.remaining, Decimal('0'))
        self.assertEqual(customer.current_balance, Decimal('0'), 'the 50 change given back must not sit as a customer credit')

        total_posted = Payment.objects.filter(customer=customer).aggregate(t=Sum('amount'))['t'] or Decimal('0')
        self.assertEqual(total_posted, Decimal('100'), 'only the invoice-covering 100 should ever be posted — the 50 excess is a wash, not a ledger entry')

    def test_walkin_sale_change_given_is_unaffected(self):
        product, warehouse = make_product()
        sale = Sale(customer=None, warehouse=warehouse, invoice_no='T-SALE-WALKIN', date='2026-07-25')
        sale = sales_services.create_sale(
            sale, [{'product': product, 'quantity': Decimal('1'), 'selling_price': Decimal('100')}], Decimal('120'), None,
        )
        sale.refresh_from_db()
        self.assertEqual(sale.paid, Decimal('120'), 'walk-in paid should be uncapped (cash tendered)')
        self.assertEqual(sale.remaining, Decimal('-20'), 'negative remaining represents change owed back')


class WhatsAppNumberNormalizationTests(TestCase):
    """wa.me needs full international digits — a local Pakistani number's
    leading 0 left in place resolves to an invalid chat (blank/black screen,
    message never sendable)."""

    def test_local_pakistani_format_gets_country_code(self):
        self.assertEqual(_whatsapp_number('0333-7654321'), '923337654321')
        self.assertEqual(_whatsapp_number('03411581043'), '923411581043')

    def test_already_international_format_is_left_alone(self):
        self.assertEqual(_whatsapp_number('+923337654321'), '923337654321')
        self.assertEqual(_whatsapp_number('923337654321'), '923337654321')

    def test_too_short_or_empty_returns_empty(self):
        self.assertEqual(_whatsapp_number('123'), '')
        self.assertEqual(_whatsapp_number(''), '')
        self.assertEqual(_whatsapp_number(None), '')


class PublicInvoiceLinkTests(TestCase):
    """The WhatsApp-shared bill link must work without login, be a real PDF,
    scoped to exactly one sale via its own token — never guessable from pk."""

    def test_public_link_serves_pdf_without_login(self):
        product, warehouse = make_product()
        sale = Sale(customer=None, warehouse=warehouse, invoice_no='T-SALE-PUBLIC', date='2026-07-25')
        sale = sales_services.create_sale(
            sale, [{'product': product, 'quantity': Decimal('1'), 'selling_price': Decimal('50')}], Decimal('50'), None,
        )
        resp = self.client.get(f'/sales/invoice/{sale.public_token}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertTrue(resp.content.startswith(b'%PDF'))

    def test_random_token_404s(self):
        import uuid
        resp = self.client.get(f'/sales/invoice/{uuid.uuid4()}/')
        self.assertEqual(resp.status_code, 404)

    def test_two_sales_get_different_tokens(self):
        product, warehouse = make_product()
        sale1 = sales_services.create_sale(
            Sale(customer=None, warehouse=warehouse, invoice_no='T-SALE-TOK1', date='2026-07-25'),
            [{'product': product, 'quantity': Decimal('1'), 'selling_price': Decimal('10')}], Decimal('10'), None,
        )
        sale2 = sales_services.create_sale(
            Sale(customer=None, warehouse=warehouse, invoice_no='T-SALE-TOK2', date='2026-07-25'),
            [{'product': product, 'quantity': Decimal('1'), 'selling_price': Decimal('10')}], Decimal('10'), None,
        )
        self.assertNotEqual(sale1.public_token, sale2.public_token)


class SaleListSearchTests(TestCase):
    def setUp(self):
        product, warehouse = make_product()
        self.customer = Customer.objects.create(name='Search Test Customer')
        sales_services.create_sale(
            Sale(customer=self.customer, warehouse=warehouse, invoice_no='T-SEARCH-A', date='2026-07-20'),
            [{'product': product, 'quantity': Decimal('1'), 'selling_price': Decimal('10')}], Decimal('10'), None,
        )
        sales_services.create_sale(
            Sale(customer=None, warehouse=warehouse, invoice_no='T-SEARCH-B', date='2026-07-25'),
            [{'product': product, 'quantity': Decimal('1'), 'selling_price': Decimal('10')}], Decimal('10'), None,
        )

    def _login(self):
        from accounts.models import User
        admin = User.objects.create_user(username='search_test_admin', password='x', role=User.Role.ADMIN)
        self.client.force_login(admin)

    def test_search_by_invoice_number(self):
        self._login()
        resp = self.client.get('/sales/', {'q': 'T-SEARCH-A'})
        invoices = {s.invoice_no for s in resp.context['sales']}
        self.assertEqual(invoices, {'T-SEARCH-A'})

    def test_search_by_customer_name(self):
        self._login()
        resp = self.client.get('/sales/', {'q': 'Search Test Customer'})
        invoices = {s.invoice_no for s in resp.context['sales']}
        self.assertEqual(invoices, {'T-SEARCH-A'})

    def test_search_by_date(self):
        self._login()
        resp = self.client.get('/sales/', {'date': '2026-07-20'})
        invoices = {s.invoice_no for s in resp.context['sales']}
        self.assertEqual(invoices, {'T-SEARCH-A'})


class SaleBillShowsAllocatedPaymentsTests(TestCase):
    """A due payment collected via the 'Allocate Payment Across Invoices'
    screen (payments.services.allocate_payment) creates a PaymentAllocation,
    not a Payment.sale row — the sale's printed bill must still show it."""

    def test_allocated_payment_appears_on_the_bill(self):
        from payments import services as payments_services
        from finance import services as fin_services

        product, warehouse = make_product()
        customer = Customer.objects.create(name='Allocation Bill Customer')
        sale = Sale(customer=customer, warehouse=warehouse, invoice_no='T-ALLOC-BILL', date='2026-07-25')
        sale = sales_services.create_sale(
            sale, [{'product': product, 'quantity': Decimal('1'), 'selling_price': Decimal('200')}], Decimal('50'), None,
        )
        self.assertEqual(sale.remaining, Decimal('150'))

        payments_services.allocate_payment(
            Payment.Direction.IN, fin_services.get_account('1000'), '2026-07-25',
            [(sale, Decimal('150'))], customer=customer,
        )
        sale.refresh_from_db()
        self.assertEqual(sale.remaining, Decimal('0'))

        from accounts.models import User
        admin = User.objects.create_user(username='alloc_bill_admin', password='x', role=User.Role.ADMIN)
        self.client.force_login(admin)

        detail_html = self.client.get(f'/sales/{sale.pk}/').content.decode()
        self.assertIn('150.00', detail_html, 'the allocated 150 must show in the sale detail Payments table')

        pdf_resp = self.client.get(f'/sales/{sale.pk}/invoice.pdf')
        self.assertEqual(pdf_resp.status_code, 200)
        self.assertTrue(pdf_resp.content.startswith(b'%PDF'))
