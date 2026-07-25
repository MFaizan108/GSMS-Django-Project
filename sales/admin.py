from django.contrib import admin
from .models import Sale, SaleItem, BatchAllocation, SalesReturn, SalesReturnItem, SalesReturnAllocation


class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 1
    readonly_fields = ('cost_price_at_sale',)


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ('invoice_no', 'customer', 'warehouse', 'date', 'total', 'paid', 'remaining', 'status', 'payment_type')
    inlines = [SaleItemInline]
    list_filter = ('status', 'payment_type', 'warehouse')


@admin.register(BatchAllocation)
class BatchAllocationAdmin(admin.ModelAdmin):
    list_display = ('sale_item', 'batch', 'quantity', 'unit_cost')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class SalesReturnItemInline(admin.TabularInline):
    model = SalesReturnItem
    extra = 0
    readonly_fields = ('unit_cost',)


@admin.register(SalesReturn)
class SalesReturnAdmin(admin.ModelAdmin):
    list_display = ('return_no', 'sale', 'date', 'total_refund', 'created_by')
    inlines = [SalesReturnItemInline]
    search_fields = ('return_no', 'sale__invoice_no')

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SalesReturnAllocation)
class SalesReturnAllocationAdmin(admin.ModelAdmin):
    list_display = ('return_item', 'batch_allocation', 'quantity')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
