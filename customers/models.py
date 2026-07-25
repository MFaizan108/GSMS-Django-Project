from django.db import models
from django.urls import reverse

from finance.models import Account, LedgerEntry


class Customer(models.Model):
    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    cnic = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    opening_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    linked_account = models.OneToOneField(Account, on_delete=models.PROTECT, null=True, blank=True, related_name='customer')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('customers:customer_detail', args=[self.pk])

    @property
    def current_balance(self):
        # Deliberately a fresh query, not self.linked_account.balance — the FK
        # descriptor caches the related Account on first access, which would
        # go stale if a payment updates the balance later in the same request.
        if not self.linked_account_id:
            return 0
        return Account.objects.filter(pk=self.linked_account_id).values_list('balance', flat=True).first() or 0

    @property
    def ledger_entries(self):
        if not self.linked_account_id:
            return LedgerEntry.objects.none()
        return LedgerEntry.objects.filter(account=self.linked_account).select_related('transaction').order_by('-transaction__date', '-id')
