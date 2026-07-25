from decimal import Decimal

from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from audit import services as audit_services
from audit.models import AuditLog
from finance import services as finance_services
from finance.models import Account, LedgerEntry, Payment
from inventory import services as inventory_services
from inventory.models import InventoryTransaction, ProductBatch, BatchStock, WarehouseStock
from .models import Sale, SaleItem, SalesReturn, BatchAllocation, SalesReturnItem, SalesReturnAllocation


def create_sale(sale, items_data, amount_paid_now, user, register=None):
    """items_data: list of dicts with keys product, quantity, selling_price.
    Raises inventory.services.InsufficientStockError (inside the atomic block,
    so nothing is left half-written) if any line can't be covered.

    `register`, if given, is which physical till this sale's cash moved
    through — see finance.services.record_payment's `register` kwarg."""
    with transaction.atomic():
        sale.created_by = user
        sale.register = register
        sale.save()

        total_cogs = Decimal('0')
        for item_data in items_data:
            allocations = inventory_services.allocate_stock_fifo(
                item_data['product'], sale.warehouse, item_data['quantity']
            )
            total_qty = sum((qty for _, qty, _ in allocations), Decimal('0'))
            total_cost = sum((qty * unit_cost for _, qty, unit_cost in allocations), Decimal('0'))
            weighted_cost = (total_cost / total_qty) if total_qty else Decimal('0')

            sale_item = SaleItem.objects.create(
                sale=sale, product=item_data['product'], quantity=item_data['quantity'],
                selling_price=item_data['selling_price'], cost_price_at_sale=weighted_cost,
            )
            for batch, qty, unit_cost in allocations:
                BatchAllocation.objects.create(sale_item=sale_item, batch=batch, quantity=qty, unit_cost=unit_cost)

            total_cogs += inventory_services.consume_allocations(
                allocations, sale.warehouse, reference=sale.invoice_no,
                reference_type=InventoryTransaction.ReferenceType.SALE, reference_id=sale.pk,
                created_by=user,
            )

        sale.recalculate()

        if sale.total:
            revenue_account = finance_services.get_account('4000')
            if sale.customer:
                ar_account = finance_services.get_or_create_party_account(
                    sale.customer, Account.Type.ASSET, Account.Subtype.AR
                )
                finance_services.post_transaction(
                    date=sale.date, memo=f'Sale Invoice #{sale.invoice_no}',
                    lines=[
                        (ar_account, LedgerEntry.EntryType.DEBIT, sale.total),
                        (revenue_account, LedgerEntry.EntryType.CREDIT, sale.total),
                    ],
                    reference=sale.invoice_no, created_by=user,
                )
                if amount_paid_now:
                    # Cash tendered beyond the invoice total is handed straight
                    # back to the customer as change — same as a walk-in sale —
                    # so only the invoice-covering part is ever recorded as a
                    # Payment. It deliberately does NOT become an on-account
                    # advance/credit: that would leave a phantom balance on the
                    # customer's ledger for cash that already left the till.
                    applied = min(amount_paid_now, sale.total)
                    finance_services.record_payment(
                        Payment.Direction.IN, applied,
                        finance_services.get_account('1000'), sale.date,
                        sale=sale, customer=sale.customer, created_by=user, register=register,
                    )
            else:
                # Walk-in cash sale: no party to post a receivable against —
                # the full total is recognised as cash received directly.
                cash_account = finance_services.get_or_create_register_account(register) if register else finance_services.get_account('1000')
                finance_services.post_transaction(
                    date=sale.date, memo=f'Sale Invoice #{sale.invoice_no}',
                    lines=[
                        (cash_account, LedgerEntry.EntryType.DEBIT, sale.total),
                        (revenue_account, LedgerEntry.EntryType.CREDIT, sale.total),
                    ],
                    reference=sale.invoice_no, created_by=user,
                )

        if total_cogs:
            cogs_account = finance_services.get_account('5000')
            inventory_account = finance_services.get_account('1200')
            finance_services.post_transaction(
                date=sale.date, memo=f'COGS for Sale #{sale.invoice_no}',
                lines=[
                    (cogs_account, LedgerEntry.EntryType.DEBIT, total_cogs),
                    (inventory_account, LedgerEntry.EntryType.CREDIT, total_cogs),
                ],
                reference=sale.invoice_no, created_by=user,
            )

        if not sale.customer:
            # Cash tendered by the cashier — may exceed total (change given back).
            sale.paid = amount_paid_now or Decimal('0')
        sale.recalculate()

        audit_services.log_action(
            user, AuditLog.Action.CREATE, 'sales', sale,
            new_data={'invoice_no': sale.invoice_no, 'total': str(sale.total), 'customer': str(sale.customer or 'Walk-in')},
        )
    return sale


def create_sales_return(sales_return, items_data, user):
    """items_data: list of dicts with keys sale_item, quantity, condition
    (SalesReturnItem.Condition). GOOD lines restock the exact batch(es) the
    goods were originally sold from (via BatchAllocation) and reverse COGS
    back to Inventory. DAMAGED/EXPIRED lines don't restock sellable
    inventory — their cost moves from COGS to Inventory Shrinkage Expense.
    Revenue is always reversed against the customer's AR (or cash for a
    walk-in sale), regardless of condition."""
    sale = sales_return.sale
    with transaction.atomic():
        sales_return.created_by = user
        sales_return.save()

        total_revenue = Decimal('0')
        total_restock_cost = Decimal('0')
        total_shrinkage_cost = Decimal('0')

        for data in items_data:
            sale_item = data['sale_item']
            qty = data['quantity']
            condition = data['condition']

            if qty <= 0:
                continue
            if qty > sale_item.returnable_quantity:
                raise ValueError(
                    f"Cannot return {qty} of {sale_item.product}: only {sale_item.returnable_quantity} returnable."
                )

            return_item = SalesReturnItem.objects.create(
                sales_return=sales_return, sale_item=sale_item, quantity=qty,
                condition=condition, unit_price=sale_item.selling_price,
            )

            remaining = qty
            line_cost = Decimal('0')
            for alloc in sale_item.allocations.select_related('batch').all():
                if remaining <= 0:
                    break
                alloc_returnable = alloc.returnable_quantity
                if alloc_returnable <= 0:
                    continue
                take = min(alloc_returnable, remaining)

                SalesReturnAllocation.objects.create(return_item=return_item, batch_allocation=alloc, quantity=take)
                line_cost += take * alloc.unit_cost
                remaining -= take

                if condition == SalesReturnItem.Condition.GOOD:
                    ProductBatch.objects.filter(pk=alloc.batch_id).update(
                        remaining_quantity=F('remaining_quantity') + take, status=ProductBatch.Status.ACTIVE,
                    )
                    bs, _ = BatchStock.objects.get_or_create(batch_id=alloc.batch_id, warehouse=sale.warehouse)
                    BatchStock.objects.filter(pk=bs.pk).update(quantity=F('quantity') + take)
                    ws, _ = WarehouseStock.objects.get_or_create(product=sale_item.product, warehouse=sale.warehouse)
                    WarehouseStock.objects.filter(pk=ws.pk).update(quantity=F('quantity') + take)
                    InventoryTransaction.objects.create(
                        product=sale_item.product, batch=alloc.batch, warehouse=sale.warehouse,
                        transaction_type=InventoryTransaction.Type.SALES_RETURN_IN,
                        quantity=take, unit_cost=alloc.unit_cost, reference=sales_return.return_no,
                        reference_type=InventoryTransaction.ReferenceType.SALES_RETURN,
                        reference_id=sales_return.pk, created_by=user,
                    )

            if remaining > 0:
                raise ValueError(f"Could not fully allocate return for {sale_item.product} against its original sale batches.")

            return_item.unit_cost = (line_cost / qty) if qty else Decimal('0')
            return_item.save(update_fields=['unit_cost'])

            if condition == SalesReturnItem.Condition.GOOD:
                inventory_services.recompute_product_stock(sale_item.product)
                total_restock_cost += line_cost
            else:
                total_shrinkage_cost += line_cost

            total_revenue += qty * sale_item.selling_price

        revenue_account = finance_services.get_account('4000')
        if total_revenue:
            if sale.customer:
                ar_account = finance_services.get_or_create_party_account(
                    sale.customer, Account.Type.ASSET, Account.Subtype.AR
                )
                finance_services.post_transaction(
                    date=sales_return.date, memo=f'Sales Return #{sales_return.return_no} (Sale #{sale.invoice_no})',
                    lines=[
                        (revenue_account, LedgerEntry.EntryType.DEBIT, total_revenue),
                        (ar_account, LedgerEntry.EntryType.CREDIT, total_revenue),
                    ],
                    reference=sales_return.return_no, created_by=user,
                )
            else:
                cash_account = finance_services.get_account('1000')
                finance_services.post_transaction(
                    date=sales_return.date, memo=f'Sales Return #{sales_return.return_no} (Sale #{sale.invoice_no})',
                    lines=[
                        (revenue_account, LedgerEntry.EntryType.DEBIT, total_revenue),
                        (cash_account, LedgerEntry.EntryType.CREDIT, total_revenue),
                    ],
                    reference=sales_return.return_no, created_by=user,
                )

        cogs_account = finance_services.get_account('5000')
        if total_restock_cost:
            inventory_account = finance_services.get_account('1200')
            finance_services.post_transaction(
                date=sales_return.date, memo=f'Sales Return restock #{sales_return.return_no}',
                lines=[
                    (inventory_account, LedgerEntry.EntryType.DEBIT, total_restock_cost),
                    (cogs_account, LedgerEntry.EntryType.CREDIT, total_restock_cost),
                ],
                reference=sales_return.return_no, created_by=user,
            )
        if total_shrinkage_cost:
            shrinkage_account = finance_services.get_account('5200')
            finance_services.post_transaction(
                date=sales_return.date, memo=f'Sales Return damaged/expired #{sales_return.return_no}',
                lines=[
                    (shrinkage_account, LedgerEntry.EntryType.DEBIT, total_shrinkage_cost),
                    (cogs_account, LedgerEntry.EntryType.CREDIT, total_shrinkage_cost),
                ],
                reference=sales_return.return_no, created_by=user,
            )

        audit_services.log_action(
            user, AuditLog.Action.SALE_RETURN, 'sales', sales_return,
            old_data={'sale': sale.invoice_no},
            new_data={'return_no': sales_return.return_no, 'total_refund': str(sales_return.total_refund)},
        )

    return sales_return


def cancel_sale(sale, user):
    """Void an invoice that was created in error, before any money or goods
    have actually moved against it — deliberately restricted to that narrow
    case rather than a general-purpose delete, per the append-only ledger
    design (see audit.AuditLog's docstring: financial records are cancelled/
    reversed, never hard-deleted).

    Reuses create_sales_return rather than writing a second reversal path —
    a full-invoice void is exactly a 100%, all-GOOD-condition return of every
    line, so it restocks inventory and reverses AR/Revenue/COGS through the
    same tested code create_sales_return already runs. Raises ValueError if
    the sale has any payment or prior return against it (those must go
    through the normal Return flow instead, since a real cash movement or
    partial return already happened)."""
    if sale.status == Sale.Status.CANCELLED:
        raise ValueError(f"Sale #{sale.invoice_no} is already cancelled.")
    if sale.payments.exists() or sale.payment_allocations.exists():
        raise ValueError(f"Cannot cancel Sale #{sale.invoice_no}: payments already exist against it. Use a Sales Return instead.")
    if sale.returns.exists():
        raise ValueError(f"Cannot cancel Sale #{sale.invoice_no}: it already has a return against it.")

    items_data = [
        {'sale_item': item, 'quantity': item.returnable_quantity, 'condition': SalesReturnItem.Condition.GOOD}
        for item in sale.items.all() if item.returnable_quantity > 0
    ]
    if not items_data:
        raise ValueError(f"Sale #{sale.invoice_no} has no items to cancel.")

    with transaction.atomic():
        void_return = SalesReturn(
            sale=sale, return_no=f"VOID-{sale.invoice_no}",
            date=timezone.localdate(), note='Invoice cancelled',
        )
        create_sales_return(void_return, items_data, user)

        Sale.objects.filter(pk=sale.pk).update(status=Sale.Status.CANCELLED, remaining=Decimal('0'))
        sale.status = Sale.Status.CANCELLED
        sale.remaining = Decimal('0')

        audit_services.log_action(
            user, AuditLog.Action.CANCEL, 'sales', sale,
            old_data={'status': 'pending/partial/paid'},
            new_data={'invoice_no': sale.invoice_no, 'status': 'cancelled'},
        )
    return sale
