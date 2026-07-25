from decimal import Decimal

from django.db import migrations


IN_TYPES = {'purchase_in', 'sales_return_in', 'adjustment_in', 'transfer_in'}
OUT_TYPES = {'sale_out', 'purchase_return_out', 'damage_out', 'lost_out', 'adjustment_out', 'transfer_out'}


def backfill_batchstock(apps, schema_editor):
    """Reconstructs per-(batch, warehouse) quantity from the append-only
    InventoryTransaction ledger, since that's the only record of which
    warehouse each historical movement happened in.

    Two groups of source rows:
      1. Transactions with a batch set — summed (signed by IN/OUT type) per
         (batch, warehouse) to get each batch's real per-warehouse split.
      2. Historical ADJUSTMENT_IN rows created with batch=None (the old
         adjust_stock() increase path, before this migration's code change)
         — these added quantity to WarehouseStock/Product.stock with no
         batch behind them. A synthetic 'LEGACY-ADJ' batch is created per
         (product, warehouse) to absorb that unbacked quantity, so nothing
         is lost and BatchStock still sums to WarehouseStock everywhere.
    """
    InventoryTransaction = apps.get_model('inventory', 'InventoryTransaction')
    ProductBatch = apps.get_model('inventory', 'ProductBatch')
    BatchStock = apps.get_model('inventory', 'BatchStock')
    Product = apps.get_model('products', 'Product')

    totals = {}  # (batch_id, warehouse_id) -> Decimal
    clamped = 0
    for row in InventoryTransaction.objects.filter(batch__isnull=False).values(
        'batch_id', 'warehouse_id', 'transaction_type', 'quantity'
    ):
        sign = Decimal('1') if row['transaction_type'] in IN_TYPES else Decimal('-1')
        key = (row['batch_id'], row['warehouse_id'])
        totals[key] = totals.get(key, Decimal('0')) + sign * row['quantity']

    created = 0
    for (batch_id, warehouse_id), qty in totals.items():
        if qty < 0:
            print(f"[backfill_batchstock] WARNING: batch {batch_id} @ warehouse {warehouse_id} "
                  f"computed negative ({qty}), clamped to 0 — pre-existing data inconsistency.")
            clamped += 1
            qty = Decimal('0')
        if qty == 0:
            continue
        BatchStock.objects.create(batch_id=batch_id, warehouse_id=warehouse_id, quantity=qty)
        created += 1

    # Legacy batch=None ADJUSTMENT_IN rows: sum unbacked quantity per (product, warehouse).
    legacy_totals = {}
    for row in InventoryTransaction.objects.filter(
        batch__isnull=True, transaction_type='adjustment_in'
    ).values('product_id', 'warehouse_id', 'quantity'):
        key = (row['product_id'], row['warehouse_id'])
        legacy_totals[key] = legacy_totals.get(key, Decimal('0')) + row['quantity']

    legacy_created = 0
    for (product_id, warehouse_id), qty in legacy_totals.items():
        if qty <= 0:
            continue
        product = Product.objects.filter(pk=product_id).first()
        unit_cost = product.purchase_price if product else Decimal('0')
        batch = ProductBatch.objects.create(
            product_id=product_id, batch_number='LEGACY-ADJ',
            unit_cost=unit_cost, initial_quantity=qty, remaining_quantity=qty, status='active',
        )
        BatchStock.objects.create(batch=batch, warehouse_id=warehouse_id, quantity=qty)
        legacy_created += 1

    print(f"[backfill_batchstock] Created {created} BatchStock rows from batch-tagged transactions "
          f"({clamped} clamped negatives), {legacy_created} legacy batches for unbacked adjustment_in quantity.")


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0005_batchstock'),
        ('products', '0002_pricing_redesign'),
    ]

    operations = [
        migrations.RunPython(backfill_batchstock, noop_reverse),
    ]
