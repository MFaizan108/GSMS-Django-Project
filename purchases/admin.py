from django.contrib import admin
from .models import Purchase, PurchaseItem, PurchaseReturn, PurchaseReturnItem, PurchaseOrder, PurchaseOrderItem


class PurchaseItemInline(admin.TabularInline):
    model = PurchaseItem
    extra = 1


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ('invoice_no', 'supplier', 'warehouse', 'date', 'total', 'paid', 'remaining', 'status')
    inlines = [PurchaseItemInline]
    list_filter = ('status', 'warehouse')


class PurchaseReturnItemInline(admin.TabularInline):
    model = PurchaseReturnItem
    extra = 0


@admin.register(PurchaseReturn)
class PurchaseReturnAdmin(admin.ModelAdmin):
    list_display = ('return_no', 'purchase', 'date', 'total_value', 'created_by')
    inlines = [PurchaseReturnItemInline]
    search_fields = ('return_no', 'purchase__invoice_no')

    def has_change_permission(self, request, obj=None):
        return False


class PurchaseOrderItemInline(admin.TabularInline):
    model = PurchaseOrderItem
    extra = 1


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ('order_no', 'supplier', 'warehouse', 'date', 'status', 'total_expected')
    inlines = [PurchaseOrderItemInline]
    list_filter = ('status', 'warehouse')
