from decimal import Decimal

from django.test import TestCase

from customers.models import Customer
from suppliers.models import Supplier
from inventory.models import Warehouse
from products.models import Product, Category, Brand, Unit
from sales.models import Sale, SaleItem
from purchases.models import Purchase, PurchaseItem
from finance.models import Payment
from finance import services as fin_services
from . import services as pay_services


def make_product():
    category = Category.objects.create(name='Payments Test Category')
    brand = Brand.objects.create(name='Payments Test Brand')
    unit = Unit.objects.create(name='Piece PT', short_name='pc')
    return Product.objects.create(name='Payments Test Product', category=category, brand=brand, unit=unit, purchase_price=Decimal('10'))


class OverpaymentGuardTests(TestCase):
    """PaymentAllocation/record_payment must never let a payment exceed an
    invoice's remaining balance — the P0 bug let money silently overpay an
    invoice with the excess never posted anywhere."""

    def setUp(self):
        self.warehouse = Warehouse.objects.filter(is_default=True).first() or Warehouse.objects.first()
        self.product = make_product()
        self.cash_account = fin_services.get_account('1000')

    def make_sale(self, total):
        customer = Customer.objects.create(name='Overpay Guard Customer')
        sale = Sale.objects.create(
            invoice_no=f'T-SALE-{Sale.objects.count()+1}', customer=customer, warehouse=self.warehouse,
            date='2026-07-25', total=total, paid=Decimal('0'), remaining=total,
        )
        SaleItem.objects.create(sale=sale, product=self.product, quantity=Decimal('1'), selling_price=total)
        return sale

    def make_purchase(self, total):
        supplier = Supplier.objects.create(name='Overpay Guard Supplier')
        purchase = Purchase.objects.create(
            invoice_no=f'T-PUR-{Purchase.objects.count()+1}', supplier=supplier, warehouse=self.warehouse,
            date='2026-07-25', total=total, paid=Decimal('0'), remaining=total,
        )
        PurchaseItem.objects.create(purchase=purchase, product=self.product, quantity=Decimal('1'), purchase_price=total)
        return purchase

    def test_allocate_payment_rejects_amount_over_remaining(self):
        sale = self.make_sale(Decimal('100'))
        with self.assertRaises(ValueError):
            pay_services.allocate_payment(
                Payment.Direction.IN, self.cash_account, '2026-07-25', [(sale, Decimal('150'))], customer=sale.customer,
            )

    def test_allocate_payment_rejects_direction_mismatch(self):
        sale = self.make_sale(Decimal('100'))
        with self.assertRaises(ValueError):
            pay_services.allocate_payment(
                Payment.Direction.OUT, self.cash_account, '2026-07-25', [(sale, Decimal('50'))], customer=sale.customer,
            )

    def test_allocate_payment_within_remaining_succeeds(self):
        sale = self.make_sale(Decimal('100'))
        pay_services.allocate_payment(
            Payment.Direction.IN, self.cash_account, '2026-07-25', [(sale, Decimal('60'))], customer=sale.customer,
        )
        sale.refresh_from_db()
        self.assertEqual(sale.paid, Decimal('60'))
        self.assertEqual(sale.remaining, Decimal('40'))

    def test_record_payment_rejects_amount_over_remaining_on_sale(self):
        sale = self.make_sale(Decimal('100'))
        with self.assertRaises(ValueError):
            fin_services.record_payment(
                Payment.Direction.IN, Decimal('150'), self.cash_account, '2026-07-25', sale=sale, customer=sale.customer,
            )

    def test_record_payment_rejects_direction_mismatch_on_purchase(self):
        purchase = self.make_purchase(Decimal('100'))
        with self.assertRaises(ValueError):
            fin_services.record_payment(
                Payment.Direction.IN, Decimal('50'), self.cash_account, '2026-07-25', purchase=purchase, supplier=purchase.supplier,
            )

    def test_on_account_payment_with_no_invoice_is_uncapped(self):
        customer = Customer.objects.create(name='On Account Customer')
        # No sale= — this is an advance/overpayment settlement, not tied to one invoice.
        fin_services.record_payment(Payment.Direction.IN, Decimal('99999'), self.cash_account, '2026-07-25', customer=customer)
        self.assertEqual(Payment.objects.filter(customer=customer).count(), 1)
