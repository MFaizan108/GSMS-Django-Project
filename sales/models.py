import uuid

from django.db import models
from django.db.models import Sum
from django.conf import settings
from django.urls import reverse
from customers.models import Customer
from products.models import Product


class Sale(models.Model):
    class PaymentType(models.TextChoices):
        CASH = 'cash', 'Cash'
        CREDIT = 'credit', 'Credit'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PAID = 'paid', 'Paid'
        PARTIAL = 'partial', 'Partial'
        CANCELLED = 'cancelled', 'Cancelled'

    invoice_no = models.CharField(max_length=50, unique=True)
    # An unguessable public identifier for sharing a read-only PDF link (e.g.
    # via WhatsApp) without requiring the customer to log in — see
    # sales.views.sale_invoice_public_pdf. Never used for anything internal.
    public_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='sales', null=True, blank=True)
    warehouse = models.ForeignKey('inventory.Warehouse', on_delete=models.PROTECT, related_name='sales')
    # Which physical till this sale's cash actually moved through, if any —
    # walk-in sales post straight to it; customer sales tag it for reporting
    # even though the cash itself is attributed via the linked Payment row.
    register = models.ForeignKey('finance.CashRegister', on_delete=models.PROTECT, null=True, blank=True, related_name='sales')
    date = models.DateField()
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    # For sales with a customer: cached sum of related Payment rows (supports
    # multiple partial payments over time). For walk-in sales (no customer):
    # set once at creation to the cash tendered by the cashier — may exceed
    # `total`, in which case `remaining` goes negative to represent change
    # given back. Either way, never edit directly — see sales.services.
    paid = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    remaining = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    payment_type = models.CharField(max_length=10, choices=PaymentType.choices, default=PaymentType.CASH)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PAID)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-id']

    def __str__(self):
        return f"Sale #{self.invoice_no}"

    def get_absolute_url(self):
        return reverse('sales:sale_detail', args=[self.pk])

    @property
    def total_profit(self):
        return sum((i.profit for i in self.items.all()), start=0)

    def recalculate(self):
        # A cancelled sale is a closed, reversed invoice — never let a later
        # recalculate() (e.g. triggered by an unrelated payment/return path)
        # silently resurrect its status.
        if self.status == self.Status.CANCELLED:
            return
        items = self.items.all()
        self.subtotal = sum((i.quantity * i.selling_price for i in items), start=0) if items else 0
        self.total = self.subtotal - self.discount + self.tax
        if self.customer_id:
            direct = self.payments.aggregate(t=Sum('amount'))['t'] or 0
            # payment_allocations: reverse accessor from payments.PaymentAllocation.sale
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


class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='sale_items')
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    selling_price = models.DecimalField(max_digits=12, decimal_places=2)
    # Snapshot of the actual weighted-average batch cost at sale time (from
    # BatchAllocation), not Product.purchase_price.
    cost_price_at_sale = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    @property
    def line_total(self):
        return self.quantity * self.selling_price

    @property
    def profit(self):
        return (self.selling_price - self.cost_price_at_sale) * self.quantity

    @property
    def returned_quantity(self):
        return self.return_items.aggregate(t=models.Sum('quantity'))['t'] or 0

    @property
    def returnable_quantity(self):
        return self.quantity - self.returned_quantity

    def __str__(self):
        return f"{self.product} x {self.quantity}"


class BatchAllocation(models.Model):
    sale_item = models.ForeignKey(SaleItem, on_delete=models.CASCADE, related_name='allocations')
    batch = models.ForeignKey('inventory.ProductBatch', on_delete=models.PROTECT, related_name='allocations')
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)

    @property
    def returned_quantity(self):
        return self.return_allocations.aggregate(t=models.Sum('quantity'))['t'] or 0

    @property
    def returnable_quantity(self):
        return self.quantity - self.returned_quantity

    def __str__(self):
        return f"{self.sale_item} <- {self.batch} x {self.quantity}"


class SalesReturn(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name='returns')
    return_no = models.CharField(max_length=50, unique=True)
    date = models.DateField()
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-id']

    def __str__(self):
        return f"Sales Return #{self.return_no}"

    @property
    def total_refund(self):
        return sum((i.quantity * i.unit_price for i in self.items.all()), start=0)


class SalesReturnItem(models.Model):
    class Condition(models.TextChoices):
        GOOD = 'good', 'Good'
        DAMAGED = 'damaged', 'Damaged'
        EXPIRED = 'expired', 'Expired'

    sales_return = models.ForeignKey(SalesReturn, on_delete=models.CASCADE, related_name='items')
    sale_item = models.ForeignKey(SaleItem, on_delete=models.PROTECT, related_name='return_items')
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    condition = models.CharField(max_length=10, choices=Condition.choices)
    # Snapshots at return time, for a stable audit trail independent of later edits.
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    @property
    def line_total(self):
        return self.quantity * self.unit_price

    @property
    def profit_reversed(self):
        return (self.unit_price - self.unit_cost) * self.quantity

    def __str__(self):
        return f"{self.sale_item.product} x {self.quantity} ({self.get_condition_display()})"


class SalesReturnAllocation(models.Model):
    """Which original BatchAllocation(s) this return line reverses, and how
    much — lets a GOOD return restock the exact batch(es) it was sold from."""
    return_item = models.ForeignKey(SalesReturnItem, on_delete=models.CASCADE, related_name='allocations')
    batch_allocation = models.ForeignKey(BatchAllocation, on_delete=models.PROTECT, related_name='return_allocations')
    quantity = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.return_item} <- {self.batch_allocation} x {self.quantity}"
