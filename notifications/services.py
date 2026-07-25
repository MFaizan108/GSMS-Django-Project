from products.models import Product
from customers.models import Customer
from suppliers.models import Supplier
from .models import Notification


def refresh_notifications():
    """Sync Notification rows with current live conditions: creates rows for
    newly-qualifying items (unread by default, existing rows' is_read is left
    untouched), and deletes rows whose condition no longer holds (e.g. a
    product was restocked above its minimum). Returns the unread count."""
    seen_keys = set()

    def upsert(ntype, reference_type, reference_id, level, title, message, link):
        seen_keys.add((ntype, reference_type, reference_id))
        Notification.objects.get_or_create(
            type=ntype, reference_type=reference_type, reference_id=reference_id,
            defaults={'level': level, 'title': title, 'message': message, 'link': link},
        )

    for p in Product.objects.filter(status=Product.Status.ACTIVE):
        if p.is_low_stock:
            upsert(
                Notification.Type.LOW_STOCK, 'product', p.pk, Notification.Level.WARNING,
                f'Low stock: {p.name}', f'{p.name} has {p.stock} left (minimum {p.minimum_stock}).',
                p.get_absolute_url(),
            )
        if p.is_expired:
            upsert(
                Notification.Type.EXPIRED, 'product', p.pk, Notification.Level.DANGER,
                f'Expired: {p.name}', f'{p.name} expired on {p.expiry_date}.', p.get_absolute_url(),
            )
        elif p.is_near_expiry:
            upsert(
                Notification.Type.NEAR_EXPIRY, 'product', p.pk, Notification.Level.WARNING,
                f'Near expiry: {p.name}', f'{p.name} expires on {p.expiry_date}.', p.get_absolute_url(),
            )

    for c in Customer.objects.all():
        if c.current_balance > 0:
            upsert(
                Notification.Type.CUSTOMER_DUE, 'customer', c.pk, Notification.Level.INFO,
                f'Customer due: {c.name}', f'{c.name} owes {c.current_balance}.', c.get_absolute_url(),
            )

    for s in Supplier.objects.all():
        if s.current_balance > 0:
            upsert(
                Notification.Type.SUPPLIER_DUE, 'supplier', s.pk, Notification.Level.INFO,
                f'Supplier due: {s.name}', f'You owe {s.name} {s.current_balance}.', s.get_absolute_url(),
            )

    stale_ids = [
        n.pk for n in Notification.objects.all()
        if (n.type, n.reference_type, n.reference_id) not in seen_keys
    ]
    if stale_ids:
        Notification.objects.filter(pk__in=stale_ids).delete()

    return Notification.objects.filter(is_read=False).count()
