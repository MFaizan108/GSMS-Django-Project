from decimal import Decimal

from django.test import TestCase

from suppliers.models import Supplier
from inventory.models import Warehouse
from products.models import Product, Category, Brand, Unit
from finance.models import Payment
from finance import services as fin_services
from .models import Purchase, PurchaseReturn
from . import services as purchase_services


def make_product():
    category = Category.objects.create(name='Purchases Test Category')
    brand = Brand.objects.create(name='Purchases Test Brand')
    unit = Unit.objects.create(name='Piece PuT', short_name='pc')
    return Product.objects.create(name='Purchases Test Product', category=category, brand=brand, unit=unit, purchase_price=Decimal('10'))


class PurchaseReturnSupplierRefundTests(TestCase):
    """A purchase return on an already-paid purchase should leave the
    supplier's balance correctly showing they owe the store money, and the
    supplier-refund path (finance.services.record_payment IN + supplier=)
    should be able to bring it back to zero."""

    def test_return_then_refund_lifecycle(self):
        warehouse = Warehouse.objects.filter(is_default=True).first() or Warehouse.objects.first()
        product = make_product()
        supplier = Supplier.objects.create(name='Refund Lifecycle Supplier')

        purchase = Purchase(supplier=supplier, warehouse=warehouse, invoice_no='T-PUR-REFUND', date='2026-07-25')
        purchase = purchase_services.create_purchase(
            purchase, [{'product': product, 'quantity': Decimal('10'), 'purchase_price': Decimal('50')}], Decimal('500'), None,
        )
        purchase.refresh_from_db()
        self.assertEqual(purchase.remaining, Decimal('0'))
        self.assertEqual(supplier.current_balance, Decimal('0'))

        purchase_item = purchase.items.first()
        purchase_return = PurchaseReturn(purchase=purchase, return_no='T-PR-REFUND', date='2026-07-25')
        purchase_services.create_purchase_return(
            purchase_return, [{'purchase_item': purchase_item, 'quantity': Decimal('4')}], None,
        )
        self.assertEqual(supplier.current_balance, Decimal('-200'), 'supplier should now owe the store 200')

        fin_services.record_payment(
            Payment.Direction.IN, Decimal('200'), fin_services.get_account('1000'), '2026-07-25',
            supplier=supplier, note='Refund received from supplier',
        )
        self.assertEqual(supplier.current_balance, Decimal('0'))
        self.assertTrue(Payment.objects.filter(supplier=supplier, direction=Payment.Direction.IN, amount=Decimal('200')).exists())

    def test_return_more_than_in_warehouse_is_rejected(self):
        """A batch physically transferred out of the receiving warehouse
        can't be returned as if it were still there — the warehouse-scoped
        BatchStock check this relies on."""
        warehouse = Warehouse.objects.filter(is_default=True).first() or Warehouse.objects.first()
        other_warehouse = Warehouse.objects.create(name='Other WH', code='T-OTHER-WH')
        product = make_product()
        supplier = Supplier.objects.create(name='Return Overdraw Supplier')

        purchase = Purchase(supplier=supplier, warehouse=warehouse, invoice_no='T-PUR-OVERDRAW', date='2026-07-25')
        purchase = purchase_services.create_purchase(
            purchase, [{'product': product, 'quantity': Decimal('10'), 'purchase_price': Decimal('50')}], Decimal('0'), None,
        )
        purchase_item = purchase.items.first()

        from inventory import services as inv_services
        from inventory.models import StockTransfer, StockTransferItem
        batch = purchase_item.batch
        transfer = StockTransfer.objects.create(transfer_no='T-TRANSFER-OVERDRAW', from_warehouse=warehouse, to_warehouse=other_warehouse, date='2026-07-25')
        StockTransferItem.objects.create(transfer=transfer, product=product, batch=batch, quantity=Decimal('8'))
        inv_services.transfer_stock(transfer)

        # Only 2 units remain physically in `warehouse` now; returning 4 must fail.
        purchase_return = PurchaseReturn(purchase=purchase, return_no='T-PR-OVERDRAW', date='2026-07-25')
        with self.assertRaises(ValueError):
            purchase_services.create_purchase_return(
                purchase_return, [{'purchase_item': purchase_item, 'quantity': Decimal('4')}], None,
            )
