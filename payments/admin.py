from django.contrib import admin
from .models import PaymentAllocation


@admin.register(PaymentAllocation)
class PaymentAllocationAdmin(admin.ModelAdmin):
    list_display = ('payment', 'sale', 'purchase', 'amount', 'created_at')

    def has_change_permission(self, request, obj=None):
        return False
