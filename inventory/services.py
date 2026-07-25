from decimal import Decimal

from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from products.models import Product
from .models import ProductBatch, BatchStock, WarehouseStock, InventoryTransaction, Warehouse


class InsufficientStockError(Exception):
    pass


def get_allowed_warehouses(user):
    """Warehouses `user` may act on. A user with no `branch` set (the
    default — admins/owners) sees every warehouse; a user restricted to one
    branch only ever sees that one."""
    if not getattr(user, 'branch_id', None):
        return Warehouse.objects.all()
    return Warehouse.objects.filter(pk=user.branch_id)


def receive_stock(product, warehouse, quantity, unit_cost, purchase=None, purchase_item=None,
                   expiry_date=None, manufacture_date=None, batch_number='', reference='',
                   reference_type='', reference_id=None, created_by=None,
                   transaction_type=InventoryTransaction.Type.PURCHASE_IN):
    """Create a new ProductBatch from a purchase (or opening stock) and add it to warehouse stock."""
    with transaction.atomic():
        batch = ProductBatch.objects.create(
            product=product, batch_number=batch_number, purchase=purchase, purchase_item=purchase_item,
            manufacture_date=manufacture_date, expiry_date=expiry_date, unit_cost=unit_cost,
            initial_quantity=quantity, remaining_quantity=quantity, status=ProductBatch.Status.ACTIVE,
        )
        InventoryTransaction.objects.create(
            product=product, batch=batch, warehouse=warehouse,
            transaction_type=transaction_type,
            quantity=quantity, unit_cost=unit_cost, reference=reference,
            reference_type=reference_type, reference_id=reference_id, created_by=created_by,
        )
        BatchStock.objects.create(batch=batch, warehouse=warehouse, quantity=quantity)
        ws, _ = WarehouseStock.objects.get_or_create(product=product, warehouse=warehouse)
        WarehouseStock.objects.filter(pk=ws.pk).update(quantity=F('quantity') + quantity)
        recompute_product_stock(product)
    return batch


def allocate_stock_fifo(product, warehouse, quantity):
    """Allocation plan covering `quantity`, ordered expiry-ascending with nulls
    last: batches with a real expiry_date are consumed soonest-expiry-first
    (FEFO), and once none remain, batches with no expiry_date are consumed
    oldest-created-first (plain FIFO by batch id / purchase order). For a
    product whose batches never carry an expiry_date this reduces to pure
    FIFO, which is the intended behavior for non-perishable products.
    Only draws from BatchStock rows for the given warehouse, so stock physically
    received into a different warehouse can never be allocated here.
    Raises InsufficientStockError if the warehouse's batch stock can't cover it.
    Returns a list of (batch, qty, unit_cost). Must be called inside a
    transaction.atomic() block that also performs the consumption — it locks
    the rows it reads (select_for_update) so a concurrent sale can't double-spend
    the same stock."""
    batch_stocks = BatchStock.objects.select_for_update().filter(
        batch__product=product, warehouse=warehouse, quantity__gt=0, batch__status=ProductBatch.Status.ACTIVE,
    ).select_related('batch').order_by(F('batch__expiry_date').asc(nulls_last=True), 'batch_id')

    allocations = []
    remaining = quantity
    for bs in batch_stocks:
        if remaining <= 0:
            break
        take = min(bs.quantity, remaining)
        if take <= 0:
            continue
        allocations.append((bs.batch, take, bs.batch.unit_cost))
        remaining -= take

    if remaining > 0:
        raise InsufficientStockError(
            f"Not enough batch stock for {product} in {warehouse}: short by {remaining}"
        )
    return allocations


def consume_allocations(allocations, warehouse, transaction_type=InventoryTransaction.Type.SALE_OUT,
                         reference='', reference_type='', reference_id=None, created_by=None):
    """Apply a FIFO allocation plan from allocate_stock_fifo: decrements batches and
    warehouse stock, writes InventoryTransaction rows, returns total cost (COGS)."""
    if not allocations:
        return Decimal('0')
    total_cost = Decimal('0')
    product = allocations[0][0].product
    with transaction.atomic():
        for batch, qty, unit_cost in allocations:
            BatchStock.objects.filter(batch=batch, warehouse=warehouse).update(quantity=F('quantity') - qty)
            ProductBatch.objects.filter(pk=batch.pk).update(remaining_quantity=F('remaining_quantity') - qty)
            batch.refresh_from_db(fields=['remaining_quantity'])
            if batch.remaining_quantity <= 0:
                ProductBatch.objects.filter(pk=batch.pk).update(status=ProductBatch.Status.DEPLETED)

            InventoryTransaction.objects.create(
                product=batch.product, batch=batch, warehouse=warehouse, transaction_type=transaction_type,
                quantity=qty, unit_cost=unit_cost, reference=reference,
                reference_type=reference_type, reference_id=reference_id, created_by=created_by,
            )
            WarehouseStock.objects.filter(product=batch.product, warehouse=warehouse).update(quantity=F('quantity') - qty)
            total_cost += qty * unit_cost

        recompute_product_stock(product)
    return total_cost


def transfer_stock(stock_transfer, created_by=None):
    with transaction.atomic():
        for item in stock_transfer.items.select_related('product', 'batch').all():
            from_bs = BatchStock.objects.select_for_update().filter(
                batch=item.batch, warehouse=stock_transfer.from_warehouse,
            ).first()
            available = from_bs.quantity if from_bs else Decimal('0')
            if available < item.quantity:
                raise InsufficientStockError(
                    f"Not enough stock of batch {item.batch} in {stock_transfer.from_warehouse}: "
                    f"available {available}, requested {item.quantity}"
                )

            InventoryTransaction.objects.create(
                product=item.product, batch=item.batch, warehouse=stock_transfer.from_warehouse,
                transaction_type=InventoryTransaction.Type.TRANSFER_OUT, quantity=item.quantity,
                unit_cost=item.batch.unit_cost, reference=stock_transfer.transfer_no,
                reference_type=InventoryTransaction.ReferenceType.TRANSFER, reference_id=stock_transfer.pk,
                created_by=created_by,
            )
            InventoryTransaction.objects.create(
                product=item.product, batch=item.batch, warehouse=stock_transfer.to_warehouse,
                transaction_type=InventoryTransaction.Type.TRANSFER_IN, quantity=item.quantity,
                unit_cost=item.batch.unit_cost, reference=stock_transfer.transfer_no,
                reference_type=InventoryTransaction.ReferenceType.TRANSFER, reference_id=stock_transfer.pk,
                created_by=created_by,
            )

            BatchStock.objects.filter(pk=from_bs.pk).update(quantity=F('quantity') - item.quantity)
            to_bs, _ = BatchStock.objects.get_or_create(batch=item.batch, warehouse=stock_transfer.to_warehouse)
            BatchStock.objects.filter(pk=to_bs.pk).update(quantity=F('quantity') + item.quantity)

            from_ws, _ = WarehouseStock.objects.get_or_create(product=item.product, warehouse=stock_transfer.from_warehouse)
            WarehouseStock.objects.filter(pk=from_ws.pk).update(quantity=F('quantity') - item.quantity)
            to_ws, _ = WarehouseStock.objects.get_or_create(product=item.product, warehouse=stock_transfer.to_warehouse)
            WarehouseStock.objects.filter(pk=to_ws.pk).update(quantity=F('quantity') + item.quantity)

        from audit import services as audit_services
        from audit.models import AuditLog
        audit_services.log_action(
            created_by, AuditLog.Action.STOCK_TRANSFER, 'inventory', stock_transfer,
            new_data={
                'transfer_no': stock_transfer.transfer_no,
                'from_warehouse': str(stock_transfer.from_warehouse),
                'to_warehouse': str(stock_transfer.to_warehouse),
            },
        )


def adjust_stock(adjustment, created_by=None):
    """Apply an already-saved StockAdjustment: moves WarehouseStock/ProductBatch and
    posts the corresponding GL entry (Inventory Adjustment Income for increases,
    Inventory Shrinkage Expense for decreases)."""
    from inventory.models import StockAdjustment  # local import avoids a module cycle at import time
    from finance import services as finance_services
    from finance.models import LedgerEntry
    from audit import services as audit_services
    from audit.models import AuditLog

    product, warehouse, qty = adjustment.product, adjustment.warehouse, adjustment.quantity
    reference = f"ADJ-{adjustment.pk}"
    ref_kwargs = dict(reference=reference, reference_type=InventoryTransaction.ReferenceType.ADJUSTMENT, reference_id=adjustment.pk)

    with transaction.atomic():
        if adjustment.adjust_type == StockAdjustment.AdjustType.INCREASE:
            # Creates a batch (rather than a bare batch=None transaction) so the
            # added quantity has BatchStock backing it and is actually sellable
            # via allocate_stock_fifo() in this warehouse. Uses the manually
            # entered cost when the user provided one, else falls back to the
            # product's default cost (previous behavior, unchanged).
            unit_cost = adjustment.unit_cost if adjustment.unit_cost is not None else product.purchase_price
            receive_stock(
                product=product, warehouse=warehouse, quantity=qty, unit_cost=unit_cost,
                batch_number=f"ADJ-{adjustment.pk}", created_by=created_by,
                transaction_type=InventoryTransaction.Type.ADJUSTMENT_IN, **ref_kwargs,
            )

            amount = qty * unit_cost
            if amount:
                inventory_account = finance_services.get_account('1200')
                income_account = finance_services.get_account('4200')
                finance_services.post_transaction(
                    date=timezone.localdate(), memo=f"Stock adjustment increase: {product}",
                    lines=[
                        (inventory_account, LedgerEntry.EntryType.DEBIT, amount),
                        (income_account, LedgerEntry.EntryType.CREDIT, amount),
                    ],
                    reference=reference, created_by=created_by,
                )
        else:
            decrease_type = {
                StockAdjustment.Reason.DAMAGE: InventoryTransaction.Type.DAMAGE_OUT,
                StockAdjustment.Reason.LOST: InventoryTransaction.Type.LOST_OUT,
            }.get(adjustment.reason, InventoryTransaction.Type.ADJUSTMENT_OUT)
            allocations = allocate_stock_fifo(product, warehouse, qty)
            cost = consume_allocations(
                allocations, warehouse, transaction_type=decrease_type, **ref_kwargs, created_by=created_by,
            )
            if cost:
                shrinkage_account = finance_services.get_account('5200')
                inventory_account = finance_services.get_account('1200')
                finance_services.post_transaction(
                    date=timezone.localdate(), memo=f"Stock adjustment decrease: {product}",
                    lines=[
                        (shrinkage_account, LedgerEntry.EntryType.DEBIT, cost),
                        (inventory_account, LedgerEntry.EntryType.CREDIT, cost),
                    ],
                    reference=reference, created_by=created_by,
                )

        audit_services.log_action(
            created_by, AuditLog.Action.STOCK_ADJUSTMENT, 'inventory', adjustment,
            new_data={'product': str(product), 'adjust_type': adjustment.adjust_type, 'quantity': str(qty), 'reason': adjustment.reason},
        )


def recompute_product_stock(product):
    total = WarehouseStock.objects.filter(product=product).aggregate(t=Sum('quantity'))['t'] or Decimal('0')
    Product.objects.filter(pk=product.pk).update(stock=total)
