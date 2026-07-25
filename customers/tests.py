from decimal import Decimal

from django.test import TestCase

from accounts.models import User
from inventory.models import Warehouse
from inventory import services as inv_services
from products.models import Product, Category, Brand, Unit
from sales.models import Sale
from sales import services as sales_services
from .models import Customer


def make_product():
    category = Category.objects.create(name='Customers Test Category')
    brand = Brand.objects.create(name='Customers Test Brand')
    unit = Unit.objects.create(name='Piece CT', short_name='pc')
    product = Product.objects.create(name='Customers Test Product', category=category, brand=brand, unit=unit, purchase_price=Decimal('10'))
    warehouse = Warehouse.objects.filter(is_default=True).first() or Warehouse.objects.first()
    inv_services.receive_stock(product=product, warehouse=warehouse, quantity=Decimal('100'), unit_cost=Decimal('10'))
    return product, warehouse


class DueCollectionAppliesToOldestInvoiceTests(TestCase):
    """Collecting baqaya — whether from the New Sale screen's 'Wasool
    Karein' button (the AJAX endpoint) or the customer page's plain 'Record
    Payment' button — must pay off the customer's oldest unpaid bill(s)
    first, not sit as an invisible on-account credit no bill ever shows."""

    def setUp(self):
        self.user = User.objects.create_user(username='due_collect_admin', password='x', role=User.Role.ADMIN)
        self.client.force_login(self.user)
        product, warehouse = make_product()
        self.customer = Customer.objects.create(name='Due Collection Customer')

        self.old_sale = sales_services.create_sale(
            Sale(customer=self.customer, warehouse=warehouse, invoice_no='T-DUE-OLD', date='2026-07-10'),
            [{'product': product, 'quantity': Decimal('1'), 'selling_price': Decimal('100')}], Decimal('0'), self.user,
        )
        self.new_sale = sales_services.create_sale(
            Sale(customer=self.customer, warehouse=warehouse, invoice_no='T-DUE-NEW', date='2026-07-25'),
            [{'product': product, 'quantity': Decimal('1'), 'selling_price': Decimal('50')}], Decimal('0'), self.user,
        )
        self.assertEqual(self.old_sale.remaining, Decimal('100'))
        self.assertEqual(self.new_sale.remaining, Decimal('50'))

    def test_ajax_due_collection_pays_off_oldest_invoice_first(self):
        resp = self.client.post(f'/customers/{self.customer.pk}/record-payment/', {'amount': '100', 'direction': 'in'})
        self.assertEqual(resp.status_code, 200)

        self.old_sale.refresh_from_db()
        self.new_sale.refresh_from_db()
        self.assertEqual(self.old_sale.remaining, Decimal('0'), 'the oldest invoice must be the one that gets paid off')
        self.assertEqual(self.new_sale.remaining, Decimal('50'), 'the newer invoice is untouched — only 100 was collected')

        detail_html = self.client.get(f'/sales/{self.old_sale.pk}/').content.decode()
        self.assertIn('100.00', detail_html, 'the collected due must now show on the old invoice it settled')

    def test_ajax_due_collection_spills_into_second_invoice_once_first_is_covered(self):
        resp = self.client.post(f'/customers/{self.customer.pk}/record-payment/', {'amount': '120', 'direction': 'in'})
        self.assertEqual(resp.status_code, 200)

        self.old_sale.refresh_from_db()
        self.new_sale.refresh_from_db()
        self.assertEqual(self.old_sale.remaining, Decimal('0'))
        self.assertEqual(self.new_sale.remaining, Decimal('30'), '100 clears the old invoice, remaining 20 applies to the new one')

    def test_ajax_due_collection_leftover_beyond_all_dues_is_on_account(self):
        resp = self.client.post(f'/customers/{self.customer.pk}/record-payment/', {'amount': '200', 'direction': 'in'})
        self.assertEqual(resp.status_code, 200)

        self.old_sale.refresh_from_db()
        self.new_sale.refresh_from_db()
        self.assertEqual(self.old_sale.remaining, Decimal('0'))
        self.assertEqual(self.new_sale.remaining, Decimal('0'))
        self.assertEqual(self.customer.current_balance, Decimal('-50'), 'the 50 left over becomes a genuine on-account credit')

    def test_plain_record_payment_form_also_applies_fifo(self):
        resp = self.client.post(f'/customers/{self.customer.pk}/payment/', {'amount': '100', 'description': ''})
        self.assertEqual(resp.status_code, 302)

        self.old_sale.refresh_from_db()
        self.new_sale.refresh_from_db()
        self.assertEqual(self.old_sale.remaining, Decimal('0'))
        self.assertEqual(self.new_sale.remaining, Decimal('50'))
