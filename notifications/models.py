from django.db import models


class Notification(models.Model):
    class Type(models.TextChoices):
        LOW_STOCK = 'low_stock', 'Low Stock'
        EXPIRED = 'expired', 'Expired'
        NEAR_EXPIRY = 'near_expiry', 'Near Expiry'
        CUSTOMER_DUE = 'customer_due', 'Customer Due'
        SUPPLIER_DUE = 'supplier_due', 'Supplier Due'

    class Level(models.TextChoices):
        INFO = 'info', 'Info'
        WARNING = 'warning', 'Warning'
        DANGER = 'danger', 'Danger'

    type = models.CharField(max_length=20, choices=Type.choices)
    level = models.CharField(max_length=10, choices=Level.choices, default=Level.WARNING)
    title = models.CharField(max_length=200)
    message = models.CharField(max_length=255)
    link = models.CharField(max_length=255, blank=True)
    # What live condition this notification tracks — lets notifications.services
    # re-sync (create/update/delete) without spamming duplicates.
    reference_type = models.CharField(max_length=20, blank=True)
    reference_id = models.PositiveIntegerField(null=True, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ('type', 'reference_type', 'reference_id')

    def __str__(self):
        return self.title
