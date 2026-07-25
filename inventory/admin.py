from django.contrib import admin
from .models import (
    Warehouse, ProductBatch, BatchStock, WarehouseStock, InventoryTransaction,
    StockTransfer, StockTransferItem, StockAdjustment,
)


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'is_default', 'active')


class BatchStockInline(admin.TabularInline):
    model = BatchStock
    extra = 0
    readonly_fields = ('warehouse', 'quantity')
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ProductBatch)
class ProductBatchAdmin(admin.ModelAdmin):
    list_display = ('product', 'batch_number', 'unit_cost', 'initial_quantity', 'remaining_quantity', 'expiry_date', 'status')
    list_filter = ('status',)
    search_fields = ('product__name', 'batch_number')
    readonly_fields = ('remaining_quantity',)
    inlines = [BatchStockInline]


@admin.register(BatchStock)
class BatchStockAdmin(admin.ModelAdmin):
    list_display = ('batch', 'warehouse', 'quantity')
    list_filter = ('warehouse',)
    search_fields = ('batch__product__name', 'batch__batch_number')


@admin.register(WarehouseStock)
class WarehouseStockAdmin(admin.ModelAdmin):
    list_display = ('product', 'warehouse', 'quantity')
    list_filter = ('warehouse',)
    search_fields = ('product__name',)


@admin.register(InventoryTransaction)
class InventoryTransactionAdmin(admin.ModelAdmin):
    list_display = ('date', 'product', 'transaction_type', 'quantity', 'unit_cost', 'warehouse', 'batch', 'reference_type', 'reference_id')
    list_filter = ('transaction_type', 'reference_type', 'warehouse')
    search_fields = ('product__name', 'reference')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class StockTransferItemInline(admin.TabularInline):
    model = StockTransferItem
    extra = 1


@admin.register(StockTransfer)
class StockTransferAdmin(admin.ModelAdmin):
    list_display = ('transfer_no', 'from_warehouse', 'to_warehouse', 'date')
    inlines = [StockTransferItemInline]


@admin.register(StockAdjustment)
class StockAdjustmentAdmin(admin.ModelAdmin):
    list_display = ('product', 'warehouse', 'adjust_type', 'quantity', 'reason', 'date', 'created_by')
    list_filter = ('adjust_type', 'reason', 'warehouse')
