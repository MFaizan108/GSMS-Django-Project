from decimal import Decimal

from django.test import TestCase
from django.db.models import Sum

from products.models import Product, Category, Brand, Unit
from .models import Warehouse, ProductBatch, BatchStock, WarehouseStock, StockTransfer, StockTransferItem, StockAdjustment
from . import services
from .services import InsufficientStockError
from audit.models import AuditLog


def make_product(name='Test Product', purchase_price=Decimal('40')):
    category = Category.objects.create(name=f'{name} Category')
    brand = Brand.objects.create(name=f'{name} Brand')
    unit = Unit.objects.create(name='Piece', short_name='pc')
    return Product.objects.create(
        name=name, category=category, brand=brand, unit=unit, purchase_price=purchase_price,
    )


class BatchStockWarehouseIsolationTests(TestCase):
    """FIFO/FEFO allocation must never draw from a batch that isn't
    physically in the requested warehouse — the P0 bug this model fixed."""

    def setUp(self):
        self.wh_a = Warehouse.objects.create(name='WH A', code='TEST-A')
        self.wh_b = Warehouse.objects.create(name='WH B', code='TEST-B')
        self.product = make_product()

    def test_cannot_allocate_stock_from_a_different_warehouse(self):
        services.receive_stock(product=self.product, warehouse=self.wh_a, quantity=Decimal('10'), unit_cost=Decimal('50'))
        with self.assertRaises(InsufficientStockError):
            services.allocate_stock_fifo(self.product, self.wh_b, Decimal('1'))

    def test_allocation_succeeds_from_the_correct_warehouse(self):
        services.receive_stock(product=self.product, warehouse=self.wh_a, quantity=Decimal('10'), unit_cost=Decimal('50'))
        allocations = services.allocate_stock_fifo(self.product, self.wh_a, Decimal('4'))
        total = sum(qty for _, qty, _ in allocations)
        self.assertEqual(total, Decimal('4'))

    def test_fefo_picks_the_earliest_expiry_first(self):
        late = services.receive_stock(
            product=self.product, warehouse=self.wh_a, quantity=Decimal('5'), unit_cost=Decimal('10'),
            expiry_date='2027-01-01',
        )
        soon = services.receive_stock(
            product=self.product, warehouse=self.wh_a, quantity=Decimal('5'), unit_cost=Decimal('20'),
            expiry_date='2026-08-01',
        )
        allocations = services.allocate_stock_fifo(self.product, self.wh_a, Decimal('3'))
        batch, qty, unit_cost = allocations[0]
        self.assertEqual(batch.pk, soon.pk, "should consume the soonest-expiring batch first")


class StockTransferTests(TestCase):
    def setUp(self):
        self.wh_a = Warehouse.objects.create(name='WH A', code='TEST-A')
        self.wh_b = Warehouse.objects.create(name='WH B', code='TEST-B')
        self.product = make_product()
        self.batch = services.receive_stock(product=self.product, warehouse=self.wh_a, quantity=Decimal('10'), unit_cost=Decimal('50'))

    def test_transfer_moves_batchstock_and_preserves_global_total(self):
        transfer = StockTransfer.objects.create(transfer_no='T-1', from_warehouse=self.wh_a, to_warehouse=self.wh_b, date='2026-07-25')
        StockTransferItem.objects.create(transfer=transfer, product=self.product, batch=self.batch, quantity=Decimal('4'))
        services.transfer_stock(transfer)

        a_qty = BatchStock.objects.get(batch=self.batch, warehouse=self.wh_a).quantity
        b_qty = BatchStock.objects.get(batch=self.batch, warehouse=self.wh_b).quantity
        self.batch.refresh_from_db()
        self.assertEqual(a_qty, Decimal('6'))
        self.assertEqual(b_qty, Decimal('4'))
        self.assertEqual(self.batch.remaining_quantity, Decimal('10'), "transfer must not change the batch's global total")

    def test_transfer_more_than_available_is_rejected(self):
        transfer = StockTransfer.objects.create(transfer_no='T-2', from_warehouse=self.wh_a, to_warehouse=self.wh_b, date='2026-07-25')
        StockTransferItem.objects.create(transfer=transfer, product=self.product, batch=self.batch, quantity=Decimal('999'))
        with self.assertRaises(InsufficientStockError):
            services.transfer_stock(transfer)

    def test_transfer_is_audit_logged(self):
        transfer = StockTransfer.objects.create(transfer_no='T-3', from_warehouse=self.wh_a, to_warehouse=self.wh_b, date='2026-07-25')
        StockTransferItem.objects.create(transfer=transfer, product=self.product, batch=self.batch, quantity=Decimal('2'))
        services.transfer_stock(transfer)
        self.assertTrue(
            AuditLog.objects.filter(action=AuditLog.Action.STOCK_TRANSFER, object_id=transfer.pk).exists()
        )


class StockAdjustmentTests(TestCase):
    def setUp(self):
        self.warehouse = Warehouse.objects.create(name='WH', code='TEST-WH', is_default=True)
        self.product = make_product(purchase_price=Decimal('40'))

    def test_increase_creates_a_real_sellable_batch(self):
        adjustment = StockAdjustment.objects.create(
            product=self.product, warehouse=self.warehouse, adjust_type=StockAdjustment.AdjustType.INCREASE,
            quantity=Decimal('5'), reason=StockAdjustment.Reason.CORRECTION,
        )
        before = ProductBatch.objects.filter(product=self.product).count()
        services.adjust_stock(adjustment)
        after = ProductBatch.objects.filter(product=self.product).count()
        self.assertEqual(after, before + 1)
        # Must be immediately sellable from that warehouse (not a phantom batch=None transaction).
        allocations = services.allocate_stock_fifo(self.product, self.warehouse, Decimal('1'))
        self.assertEqual(len(allocations), 1)

    def test_manual_unit_cost_overrides_product_default(self):
        adjustment = StockAdjustment.objects.create(
            product=self.product, warehouse=self.warehouse, adjust_type=StockAdjustment.AdjustType.INCREASE,
            quantity=Decimal('5'), unit_cost=Decimal('77.50'), reason=StockAdjustment.Reason.CORRECTION,
        )
        services.adjust_stock(adjustment)
        batch = ProductBatch.objects.filter(product=self.product).order_by('-id').first()
        self.assertEqual(batch.unit_cost, Decimal('77.50'))

    def test_blank_unit_cost_falls_back_to_product_default(self):
        adjustment = StockAdjustment.objects.create(
            product=self.product, warehouse=self.warehouse, adjust_type=StockAdjustment.AdjustType.INCREASE,
            quantity=Decimal('5'), reason=StockAdjustment.Reason.CORRECTION,
        )
        services.adjust_stock(adjustment)
        batch = ProductBatch.objects.filter(product=self.product).order_by('-id').first()
        self.assertEqual(batch.unit_cost, self.product.purchase_price)


class BatchStockIntegrityTests(TestCase):
    """Cross-checks the cache hierarchy BatchStock -> WarehouseStock -> Product.stock
    stays consistent through receive/consume, the same invariant the P0 migration
    backfill relies on."""

    def test_receive_and_consume_keep_caches_in_sync(self):
        warehouse = Warehouse.objects.create(name='WH', code='TEST-SYNC')
        product = make_product()
        services.receive_stock(product=product, warehouse=warehouse, quantity=Decimal('20'), unit_cost=Decimal('10'))

        ws = WarehouseStock.objects.get(product=product, warehouse=warehouse)
        bs_total = BatchStock.objects.filter(batch__product=product, warehouse=warehouse).aggregate(t=Sum('quantity'))['t']
        self.assertEqual(ws.quantity, bs_total)

        allocations = services.allocate_stock_fifo(product, warehouse, Decimal('7'))
        services.consume_allocations(allocations, warehouse)

        product.refresh_from_db()
        ws.refresh_from_db()
        self.assertEqual(ws.quantity, Decimal('13'))
        self.assertEqual(product.stock, Decimal('13'))
