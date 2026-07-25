from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from audit import services as audit_services
from audit.models import AuditLog
from finance import services as finance_services
from finance.models import Account, LedgerEntry, Payment
from inventory import services as inventory_services
from inventory.models import InventoryTransaction, ProductBatch, BatchStock, WarehouseStock
from .models import Purchase, PurchaseItem, PurchaseReturn, PurchaseReturnItem, PurchaseOrder, PurchaseOrderItem


def create_purchase_order(purchase_order, items_data, user):
    """items_data: list of dicts with keys product, quantity, expected_price.
    Pure planning document — no inventory or GL impact."""
    with transaction.atomic():
        purchase_order.created_by = user
        purchase_order.save()
        for item_data in items_data:
            PurchaseOrderItem.objects.create(
                purchase_order=purchase_order, product=item_data['product'],
                quantity=item_data['quantity'], expected_price=item_data['expected_price'],
            )
        audit_services.log_action(
            user, AuditLog.Action.CREATE, 'purchases', purchase_order,
            new_data={'order_no': purchase_order.order_no, 'supplier': str(purchase_order.supplier)},
        )
    return purchase_order


def create_purchase(purchase, items_data, amount_paid_now, user, register=None):
    """items_data: list of dicts with keys product, quantity, purchase_price,
    expiry_date (optional), batch_number (optional), purchase_order_item (optional
    — set when this line fulfills a PurchaseOrderItem).

    `register`, if given, is which physical till the amount_paid_now cash
    actually came out of — see finance.services.record_payment's `register`
    kwarg."""
    with transaction.atomic():
        purchase.created_by = user
        purchase.save()

        touched_orders = set()
        for item_data in items_data:
            item = PurchaseItem.objects.create(
                purchase=purchase,
                product=item_data['product'],
                quantity=item_data['quantity'],
                purchase_price=item_data['purchase_price'],
                expiry_date=item_data.get('expiry_date'),
                purchase_order_item=item_data.get('purchase_order_item'),
            )
            if item.purchase_order_item_id:
                touched_orders.add(item.purchase_order_item.purchase_order_id)
            inventory_services.receive_stock(
                product=item.product, warehouse=purchase.warehouse, quantity=item.quantity,
                unit_cost=item.purchase_price, purchase=purchase, purchase_item=item,
                expiry_date=item.expiry_date, batch_number=item_data.get('batch_number', ''),
                reference=purchase.invoice_no,
                reference_type=InventoryTransaction.ReferenceType.PURCHASE, reference_id=purchase.pk,
                created_by=user,
            )
            product = item.product
            update_fields = ['purchase_price']
            product.purchase_price = item.purchase_price
            if item.expiry_date:
                product.expiry_date = item.expiry_date
                update_fields.append('expiry_date')
            product.save(update_fields=update_fields)

        purchase.recalculate()

        if purchase.total:
            inventory_account = finance_services.get_account('1200')
            ap_account = finance_services.get_or_create_party_account(
                purchase.supplier, Account.Type.LIABILITY, Account.Subtype.AP
            )
            finance_services.post_transaction(
                date=purchase.date, memo=f'Purchase Invoice #{purchase.invoice_no}',
                lines=[
                    (inventory_account, LedgerEntry.EntryType.DEBIT, purchase.total),
                    (ap_account, LedgerEntry.EntryType.CREDIT, purchase.total),
                ],
                reference=purchase.invoice_no, created_by=user,
            )
            if amount_paid_now:
                finance_services.record_payment(
                    Payment.Direction.OUT, min(amount_paid_now, purchase.total),
                    finance_services.get_account('1000'), purchase.date,
                    purchase=purchase, supplier=purchase.supplier, created_by=user, register=register,
                )

        purchase.recalculate()

        for order_id in touched_orders:
            PurchaseOrder.objects.get(pk=order_id).refresh_status()

        audit_services.log_action(
            user, AuditLog.Action.CREATE, 'purchases', purchase,
            new_data={'invoice_no': purchase.invoice_no, 'total': str(purchase.total), 'supplier': str(purchase.supplier)},
        )
    return purchase


def create_purchase_return(purchase_return, items_data, user):
    """items_data: list of dicts with keys purchase_item, quantity. Each
    PurchaseItem maps to exactly one ProductBatch (they're a OneToOne), so a
    return decrements that batch directly — it can only return quantity still
    physically in stock (not yet sold/transferred elsewhere)."""
    purchase = purchase_return.purchase
    with transaction.atomic():
        purchase_return.created_by = user
        purchase_return.save()

        total_cost = Decimal('0')
        for data in items_data:
            purchase_item = data['purchase_item']
            qty = data['quantity']
            if qty <= 0:
                continue
            if qty > purchase_item.returnable_quantity:
                raise ValueError(
                    f"Cannot return {qty} of {purchase_item.product}: only {purchase_item.returnable_quantity} returnable."
                )
            batch = getattr(purchase_item, 'batch', None)
            if batch is None:
                raise ValueError(f"No batch found for {purchase_item.product} — cannot return.")
            if qty > batch.remaining_quantity:
                raise ValueError(
                    f"Cannot return {qty} of {purchase_item.product}: only {batch.remaining_quantity} still in stock "
                    f"(the rest has already been sold or moved)."
                )
            batch_stock = BatchStock.objects.select_for_update().filter(batch=batch, warehouse=purchase.warehouse).first()
            available_here = batch_stock.quantity if batch_stock else Decimal('0')
            if qty > available_here:
                raise ValueError(
                    f"Cannot return {qty} of {purchase_item.product}: only {available_here} still in stock at "
                    f"{purchase.warehouse} (the rest has already been sold or transferred elsewhere)."
                )

            PurchaseReturnItem.objects.create(
                purchase_return=purchase_return, purchase_item=purchase_item, quantity=qty,
                unit_cost=purchase_item.purchase_price,
            )

            BatchStock.objects.filter(pk=batch_stock.pk).update(quantity=F('quantity') - qty)
            ProductBatch.objects.filter(pk=batch.pk).update(remaining_quantity=F('remaining_quantity') - qty)
            WarehouseStock.objects.filter(product=purchase_item.product, warehouse=purchase.warehouse).update(
                quantity=F('quantity') - qty
            )
            InventoryTransaction.objects.create(
                product=purchase_item.product, batch=batch, warehouse=purchase.warehouse,
                transaction_type=InventoryTransaction.Type.PURCHASE_RETURN_OUT,
                quantity=qty, unit_cost=purchase_item.purchase_price, reference=purchase_return.return_no,
                reference_type=InventoryTransaction.ReferenceType.PURCHASE_RETURN,
                reference_id=purchase_return.pk, created_by=user,
            )
            inventory_services.recompute_product_stock(purchase_item.product)
            total_cost += qty * purchase_item.purchase_price

        if total_cost:
            inventory_account = finance_services.get_account('1200')
            ap_account = finance_services.get_or_create_party_account(
                purchase.supplier, Account.Type.LIABILITY, Account.Subtype.AP
            )
            finance_services.post_transaction(
                date=purchase_return.date, memo=f'Purchase Return #{purchase_return.return_no} (Purchase #{purchase.invoice_no})',
                lines=[
                    (ap_account, LedgerEntry.EntryType.DEBIT, total_cost),
                    (inventory_account, LedgerEntry.EntryType.CREDIT, total_cost),
                ],
                reference=purchase_return.return_no, created_by=user,
            )

        audit_services.log_action(
            user, AuditLog.Action.PURCHASE_RETURN, 'purchases', purchase_return,
            old_data={'purchase': purchase.invoice_no},
            new_data={'return_no': purchase_return.return_no, 'total_value': str(purchase_return.total_value)},
        )
    return purchase_return


def cancel_purchase(purchase, user):
    """Void an invoice that was created in error, before any money has moved
    and while all the received stock is still on hand — mirrors
    sales.services.cancel_sale. Reuses create_purchase_return for the actual
    reversal (a full-invoice void is a 100% return of every line), so it's
    naturally blocked with the same ValueError create_purchase_return already
    raises if any of the received stock has since been sold or transferred
    elsewhere — that stock physically left the building, so cancelling the
    purchase that brought it in is no longer possible; a Purchase Return for
    what's still on hand is the correct tool instead."""
    if purchase.status == Purchase.Status.CANCELLED:
        raise ValueError(f"Purchase #{purchase.invoice_no} is already cancelled.")
    if purchase.payments.exists() or purchase.payment_allocations.exists():
        raise ValueError(f"Cannot cancel Purchase #{purchase.invoice_no}: payments already exist against it. Use a Purchase Return instead.")
    if purchase.returns.exists():
        raise ValueError(f"Cannot cancel Purchase #{purchase.invoice_no}: it already has a return against it.")

    items_data = [
        {'purchase_item': item, 'quantity': item.returnable_quantity}
        for item in purchase.items.all() if item.returnable_quantity > 0
    ]
    if not items_data:
        raise ValueError(f"Purchase #{purchase.invoice_no} has no items to cancel.")

    with transaction.atomic():
        void_return = PurchaseReturn(
            purchase=purchase, return_no=f"VOID-{purchase.invoice_no}",
            date=timezone.localdate(), note='Invoice cancelled',
        )
        create_purchase_return(void_return, items_data, user)

        Purchase.objects.filter(pk=purchase.pk).update(status=Purchase.Status.CANCELLED, remaining=Decimal('0'))
        purchase.status = Purchase.Status.CANCELLED
        purchase.remaining = Decimal('0')

        audit_services.log_action(
            user, AuditLog.Action.CANCEL, 'purchases', purchase,
            old_data={'status': 'pending/partial/paid'},
            new_data={'invoice_no': purchase.invoice_no, 'status': 'cancelled'},
        )
    return purchase
