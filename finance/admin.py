from django.contrib import admin
from .models import Account, BusinessTransaction, LedgerEntry, Payment, Expense, Income, DayClosing, CashRegister, CashTransaction


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'type', 'subtype', 'balance', 'is_active')
    list_filter = ('type', 'subtype', 'is_active')
    search_fields = ('code', 'name')
    readonly_fields = ('balance',)


class LedgerEntryInline(admin.TabularInline):
    model = LedgerEntry
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(BusinessTransaction)
class BusinessTransactionAdmin(admin.ModelAdmin):
    list_display = ('date', 'memo', 'reference', 'created_by', 'created_at')
    list_filter = ('date',)
    search_fields = ('memo', 'reference')
    inlines = [LedgerEntryInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    list_display = ('transaction', 'account', 'entry_type', 'amount')
    list_filter = ('entry_type', 'account')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('date', 'direction', 'amount', 'account', 'customer', 'supplier', 'sale', 'purchase')
    list_filter = ('direction', 'account')

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ('title', 'amount', 'date', 'account')
    list_filter = ('date', 'account')


@admin.register(Income)
class IncomeAdmin(admin.ModelAdmin):
    list_display = ('title', 'amount', 'date', 'account')
    list_filter = ('date', 'account')


@admin.register(DayClosing)
class DayClosingAdmin(admin.ModelAdmin):
    list_display = ('date', 'opening_cash', 'expected_cash', 'actual_cash', 'difference', 'created_by')
    list_filter = ('date',)

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(CashRegister)
class CashRegisterAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'warehouse', 'current_balance', 'is_active')


@admin.register(CashTransaction)
class CashTransactionAdmin(admin.ModelAdmin):
    list_display = ('register', 'transaction_type', 'direction', 'amount', 'balance_after', 'created_at')
    list_filter = ('transaction_type', 'direction', 'register')

    def has_change_permission(self, request, obj=None):
        return False
