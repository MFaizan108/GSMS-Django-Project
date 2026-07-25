from django.db import models
from django.db.models import Sum
from django.conf import settings
from django.urls import reverse
from suppliers.models import Supplier
from products.models import Product


class PurchaseOrder(models.Model):
    """The optional pre-invoice step: what was ordered from a supplier,
    before any goods, batches, or GL postings exist. Converting a PO into a
    real Purchase (invoice) is a separate, explicit action — a PurchaseOrder
    by itself never touches inventory or the ledger."""
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        SENT = 'sent', 'Sent to Supplier'
        PARTIALLY_RECEIVED = 'partially_received', 'Partially Received'
        RECEIVED = 'received', 'Fully Received'
        CANCELLED = 'cancelled', 'Cancelled'

    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='purchase_orders')
    warehouse = models.ForeignKey('inventory.Warehouse', on_delete=models.PROTECT, related_name='purchase_orders')
    order_no = models.CharField(max_length=50, unique=True)
    date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-id']

    def __str__(self):
        return f"PO #{self.order_no}"

    def get_absolute_url(self):
        return reverse('purchases:purchase_order_detail', args=[self.pk])

    @property
    def total_expected(self):
        return sum((i.line_total for i in self.items.all()), start=0)

    def refresh_status(self):
        items = list(self.items.all())
        if not items or self.status == self.Status.CANCELLED:
            return
        if all(i.pending_quantity <= 0 for i in items):
            self.status = self.Status.RECEIVED
        elif any(i.received_quantity > 0 for i in items):
            self.status = self.Status.PARTIALLY_RECEIVED
        self.save(update_fields=['status'])


class PurchaseOrderItem(models.Model):
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='purchase_order_items')
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    expected_price = models.DecimalField(max_digits=12, decimal_places=2)

    @property
    def line_total(self):
        return self.quantity * self.expected_price

    @property
    def received_quantity(self):
        return self.purchase_items.aggregate(t=Sum('quantity'))['t'] or 0

    @property
    def pending_quantity(self):
        return self.quantity - self.received_quantity

    def __str__(self):
        return f"{self.product} x {self.quantity}"


class Purchase(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PAID = 'paid', 'Paid'
        PARTIAL = 'partial', 'Partial'
        CANCELLED = 'cancelled', 'Cancelled'

    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='purchases')
    warehouse = models.ForeignKey('inventory.Warehouse', on_delete=models.PROTECT, related_name='purchases')
    invoice_no = models.CharField(max_length=50, unique=True)
    date = models.DateField()
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    # Cached from the related Payment rows by recalculate() — never set directly.
    paid = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    remaining = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-id']

    def __str__(self):
        return f"Purchase #{self.invoice_no}"

    def get_absolute_url(self):
        return reverse('purchases:purchase_detail', args=[self.pk])

    def recalculate(self):
        # A cancelled purchase is a closed, reversed invoice — never let a later
        # recalculate() silently resurrect its status.
        if self.status == self.Status.CANCELLED:
            return
        items = self.items.all()
        self.subtotal = sum((i.quantity * i.purchase_price for i in items), start=0) if items else 0
        self.total = self.subtotal - self.discount + self.tax
        direct = self.payments.aggregate(t=Sum('amount'))['t'] or 0
        # payment_allocations: reverse accessor from payments.PaymentAllocation.purchase
        # (registered once that app is installed — no import needed here).
        allocated = self.payment_allocations.aggregate(t=Sum('amount'))['t'] or 0
        self.paid = direct + allocated
        self.remaining = self.total - self.paid
        if self.remaining <= 0:
            self.status = self.Status.PAID
        elif self.paid > 0:
            self.status = self.Status.PARTIAL
        else:
            self.status = self.Status.PENDING
        self.save()


class PurchaseItem(models.Model):
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='purchase_items')
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    purchase_price = models.DecimalField(max_digits=12, decimal_places=2)
    expiry_date = models.DateField(null=True, blank=True)
    # Set when this line fulfills (all or part of) a PurchaseOrderItem — optional,
    # since a Purchase Order is never mandatory before invoicing.
    purchase_order_item = models.ForeignKey(
        PurchaseOrderItem, on_delete=models.SET_NULL, null=True, blank=True, related_name='purchase_items'
    )

    @property
    def line_total(self):
        return self.quantity * self.purchase_price

    @property
    def returned_quantity(self):
        return self.return_items.aggregate(t=Sum('quantity'))['t'] or 0

    @property
    def returnable_quantity(self):
        return self.quantity - self.returned_quantity

    def __str__(self):
        return f"{self.product} x {self.quantity}"


class PurchaseReturn(models.Model):
    purchase = models.ForeignKey(Purchase, on_delete=models.PROTECT, related_name='returns')
    return_no = models.CharField(max_length=50, unique=True)
    date = models.DateField()
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-id']

    def __str__(self):
        return f"Purchase Return #{self.return_no}"

    @property
    def total_value(self):
        return sum((i.quantity * i.unit_cost for i in self.items.all()), start=0)


class PurchaseReturnItem(models.Model):
    purchase_return = models.ForeignKey(PurchaseReturn, on_delete=models.CASCADE, related_name='items')
    purchase_item = models.ForeignKey(PurchaseItem, on_delete=models.PROTECT, related_name='return_items')
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    # Snapshot at return time, for a stable audit trail independent of later edits.
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)

    @property
    def line_total(self):
        return self.quantity * self.unit_cost

    def __str__(self):
        return f"{self.purchase_item.product} x {self.quantity}"
