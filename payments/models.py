from django.db import models


class PaymentAllocation(models.Model):
    """How one finance.Payment (a single real-world cash movement) is split
    across multiple outstanding invoices. A Payment either targets exactly
    one Sale/Purchase directly (the common case, unchanged) or has one or
    more PaymentAllocation rows (the multi-invoice case) — never both."""
    payment = models.ForeignKey('finance.Payment', on_delete=models.CASCADE, related_name='allocations')
    sale = models.ForeignKey('sales.Sale', on_delete=models.PROTECT, null=True, blank=True, related_name='payment_allocations')
    purchase = models.ForeignKey('purchases.Purchase', on_delete=models.PROTECT, null=True, blank=True, related_name='payment_allocations')
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(sale__isnull=False, purchase__isnull=True)
                    | models.Q(sale__isnull=True, purchase__isnull=False)
                ),
                name='paymentallocation_exactly_one_target',
            ),
        ]

    def __str__(self):
        target = self.sale or self.purchase
        return f"{self.payment} -> {target}: {self.amount}"
