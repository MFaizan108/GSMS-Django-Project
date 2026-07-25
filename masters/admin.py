from django.contrib import admin
from .models import (
    Tax, PaymentMethod, Branch, ExpenseCategory, IncomeCategory,
    CustomerType, SupplierType, PriceLevel,
)


@admin.register(Tax)
class TaxAdmin(admin.ModelAdmin):
    list_display = ('name', 'rate', 'is_active')


@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'is_active')
    prepopulated_fields = {'code': ('name',)}


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'phone', 'is_active')
    search_fields = ('name', 'code')


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active')


@admin.register(IncomeCategory)
class IncomeCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active')


@admin.register(CustomerType)
class CustomerTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active')


@admin.register(SupplierType)
class SupplierTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active')


@admin.register(PriceLevel)
class PriceLevelAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_default', 'is_active')
