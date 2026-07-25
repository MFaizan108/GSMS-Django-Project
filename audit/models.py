from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """Append-only. Never updated or deleted — financial records are
    cancelled/voided/reversed (e.g. via Returns), never hard-deleted, and
    this log is the trail of who did what and when."""

    class Action(models.TextChoices):
        CREATE = 'create', 'Create'
        UPDATE = 'update', 'Update'
        DELETE = 'delete', 'Delete'
        PRICE_CHANGE = 'price_change', 'Price Change'
        STOCK_ADJUSTMENT = 'stock_adjustment', 'Stock Adjustment'
        PAYMENT = 'payment', 'Payment'
        SALE_RETURN = 'sale_return', 'Sale Return'
        PURCHASE_RETURN = 'purchase_return', 'Purchase Return'
        LOGIN = 'login', 'Login'
        LOGOUT = 'logout', 'Logout'
        FAILED_LOGIN = 'failed_login', 'Failed Login'
        ROLE_CHANGE = 'role_change', 'Role Change'
        STOCK_TRANSFER = 'stock_transfer', 'Stock Transfer'
        DAY_CLOSING = 'day_closing', 'Day Closing'
        CASH_REGISTER_TRANSACTION = 'cash_register_transaction', 'Cash Register Transaction'
        CANCEL = 'cancel', 'Cancel'
        BALANCE_ADJUSTMENT = 'balance_adjustment', 'Balance Adjustment'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=30, choices=Action.choices)
    module = models.CharField(max_length=50)
    object_type = models.CharField(max_length=100)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    object_repr = models.CharField(max_length=255, blank=True)
    old_data = models.JSONField(null=True, blank=True)
    new_data = models.JSONField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['object_type', 'object_id']),
        ]

    def __str__(self):
        return f"{self.get_action_display()} {self.object_type} #{self.object_id} by {self.user}"
