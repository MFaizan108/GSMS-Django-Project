from django.db import models
from django.conf import settings
from products.models import Product


class Warehouse(models.Model):
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=20, unique=True)
    address = models.TextField(blank=True)
    is_default = models.BooleanField(default=False)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class ProductBatch(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        DEPLETED = 'depleted', 'Depleted'
        EXPIRED = 'expired', 'Expired'

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='batches')
    batch_number = models.CharField(max_length=50, blank=True)
    purchase = models.ForeignKey('purchases.Purchase', on_delete=models.PROTECT, null=True, blank=True, related_name='batches')
    purchase_item = models.OneToOneField('purchases.PurchaseItem', on_delete=models.PROTECT, null=True, blank=True, related_name='batch')

    manufacture_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)

    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)
    initial_quantity = models.DecimalField(max_digits=12, decimal_places=2)
    # Cached — maintained only by inventory.services.
    remaining_quantity = models.DecimalField(max_digits=12, decimal_places=2, editable=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['expiry_date', 'id']

    def __str__(self):
        return f"{self.product} batch {self.batch_number or self.pk}"


class BatchStock(models.Model):
    """Per-warehouse quantity of a batch — the real source of truth FIFO/FEFO
    allocation reads from. ProductBatch.remaining_quantity and
    WarehouseStock.quantity are cached rollups derived from this."""
    batch = models.ForeignKey(ProductBatch, on_delete=models.PROTECT, related_name='stocks')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='batch_stocks')
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        unique_together = ('batch', 'warehouse')
        constraints = [
            models.CheckConstraint(check=models.Q(quantity__gte=0), name='batchstock_quantity_gte_0'),
        ]

    def __str__(self):
        return f"{self.batch} @ {self.warehouse}: {self.quantity}"


class WarehouseStock(models.Model):
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='warehouse_stocks')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='stocks')
    # Cached rollup — maintained only by inventory.services.
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)

    class Meta:
        unique_together = ('product', 'warehouse')

    def __str__(self):
        return f"{self.product} @ {self.warehouse}: {self.quantity}"


class InventoryTransaction(models.Model):
    class Type(models.TextChoices):
        PURCHASE_IN = 'purchase_in', 'Purchase In'
        SALE_OUT = 'sale_out', 'Sale Out'
        SALES_RETURN_IN = 'sales_return_in', 'Sales Return In'
        PURCHASE_RETURN_OUT = 'purchase_return_out', 'Purchase Return Out'
        DAMAGE_OUT = 'damage_out', 'Damage Out'
        LOST_OUT = 'lost_out', 'Lost Out'
        ADJUSTMENT_IN = 'adjustment_in', 'Adjustment In'
        ADJUSTMENT_OUT = 'adjustment_out', 'Adjustment Out'
        TRANSFER_IN = 'transfer_in', 'Transfer In'
        TRANSFER_OUT = 'transfer_out', 'Transfer Out'

    class ReferenceType(models.TextChoices):
        PURCHASE = 'purchase', 'Purchase'
        SALE = 'sale', 'Sale'
        PURCHASE_RETURN = 'purchase_return', 'Purchase Return'
        SALES_RETURN = 'sales_return', 'Sales Return'
        ADJUSTMENT = 'adjustment', 'Adjustment'
        TRANSFER = 'transfer', 'Transfer'

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='inventory_transactions')
    batch = models.ForeignKey(ProductBatch, on_delete=models.PROTECT, null=True, blank=True, related_name='transactions')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='transactions')
    transaction_type = models.CharField(max_length=20, choices=Type.choices)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)
    # Human-readable label (e.g. an invoice number) kept alongside the
    # structured reference_type/reference_id pair used for actual lookups.
    reference = models.CharField(max_length=100, blank=True)
    reference_type = models.CharField(max_length=20, choices=ReferenceType.choices, blank=True)
    reference_id = models.PositiveIntegerField(null=True, blank=True)
    date = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['-date', '-id']
        indexes = [
            models.Index(fields=['reference_type', 'reference_id']),
        ]

    def __str__(self):
        return f"{self.get_transaction_type_display()} {self.product} x {self.quantity} @ {self.warehouse}"


class StockTransfer(models.Model):
    transfer_no = models.CharField(max_length=50, unique=True)
    from_warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='transfers_out')
    to_warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='transfers_in')
    date = models.DateField()
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-id']

    def __str__(self):
        return f"Transfer #{self.transfer_no}"


class StockTransferItem(models.Model):
    transfer = models.ForeignKey(StockTransfer, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='transfer_items')
    batch = models.ForeignKey(ProductBatch, on_delete=models.PROTECT, related_name='transfer_items')
    quantity = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.product} x {self.quantity}"


class StockAdjustment(models.Model):
    class Reason(models.TextChoices):
        DAMAGE = 'damage', 'Damage'
        LOST = 'lost', 'Lost'
        RETURNED = 'returned', 'Returned'
        CORRECTION = 'correction', 'Manual Correction'
        OTHER = 'other', 'Other'

    class AdjustType(models.TextChoices):
        INCREASE = 'increase', 'Stock In (+)'
        DECREASE = 'decrease', 'Stock Out (-)'

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='adjustments')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='adjustments')
    adjust_type = models.CharField(max_length=10, choices=AdjustType.choices)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    # Only meaningful for INCREASE — the actual cost of the stock being added
    # (e.g. a supplier gift, a stocktake correction at a known cost). Left
    # blank, inventory.services.adjust_stock() falls back to
    # product.purchase_price, same as before this field existed. Ignored for
    # DECREASE, whose cost always comes from FIFO consumption of real batches.
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    reason = models.CharField(max_length=20, choices=Reason.choices, default=Reason.CORRECTION)
    note = models.CharField(max_length=255, blank=True)
    date = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f"{self.product} {self.get_adjust_type_display()} {self.quantity}"
