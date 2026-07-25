from django.contrib import admin
from .models import Supplier


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'company', 'phone', 'current_balance')
    search_fields = ('name', 'company', 'phone')
