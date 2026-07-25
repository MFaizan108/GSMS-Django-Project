from django.conf import settings
from django.db import models


class Account(models.Model):
    """Chart-of-accounts entry. balance is a cache maintained exclusively by
    finance.services.post_transaction — never edit it directly."""

    class Type(models.TextChoices):
        ASSET = 'asset', 'Asset'
        LIABILITY = 'liability', 'Liability'
        EQUITY = 'equity', 'Equity'
        INCOME = 'income', 'Income'
        EXPENSE = 'expense', 'Expense'

    class Subtype(models.TextChoices):
        CASH = 'cash', 'Cash'
        BANK = 'bank', 'Bank'
        MOBILE_WALLET = 'mobile_wallet', 'Mobile Wallet'
        OTHER = 'other', 'Other'
        AR = 'ar', 'Accounts Receivable'
        AP = 'ap', 'Accounts Payable'
        INVENTORY = 'inventory', 'Inventory'

    # Account types whose balance increases on a debit (decreases on credit).
    # Liability/Equity/Income accounts do the opposite (increase on credit).
    DEBIT_INCREASES = {Type.ASSET, Type.EXPENSE}

    # Subtypes a Payment is allowed to move money through (real cash/bank/wallet accounts).
    PAYMENT_SUBTYPES = {Subtype.CASH, Subtype.BANK, Subtype.MOBILE_WALLET, Subtype.OTHER}

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=150)
    type = models.CharField(max_length=10, choices=Type.choices)
    subtype = models.CharField(max_length=20, choices=Subtype.choices, blank=True)
    balance = models.DecimalField(max_digits=16, decimal_places=2, default=0, editable=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['code']

    def __str__(self):
        return f"{self.code} - {self.name}"


class BusinessTransaction(models.Model):
    """One balanced journal entry. Created only via finance.services.post_transaction."""

    date = models.DateField()
    memo = models.CharField(max_length=255)
    reference = models.CharField(max_length=100, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-id']

    def __str__(self):
        return f"{self.date} - {self.memo}"


class LedgerEntry(models.Model):
    """Append-only double-entry row. Never updated or deleted after creation."""

    class EntryType(models.TextChoices):
        DEBIT = 'debit', 'Debit'
        CREDIT = 'credit', 'Credit'

    transaction = models.ForeignKey(BusinessTransaction, on_delete=models.PROTECT, related_name='entries')
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='entries')
    entry_type = models.CharField(max_length=10, choices=EntryType.choices)
    amount = models.DecimalField(max_digits=16, decimal_places=2)

    class Meta:
        ordering = ['-transaction__date', '-id']
        verbose_name_plural = 'Ledger entries'

    def __str__(self):
        return f"{self.account} {self.entry_type} {self.amount}"


class Payment(models.Model):
    """A single payment covering a Sale/Purchase invoice, or an on-account
    payment against a Customer/Supplier balance not tied to one invoice.
    Multiple Payments may exist per Sale/Purchase."""

    class Direction(models.TextChoices):
        IN = 'in', 'Received'
        OUT = 'out', 'Paid'

    sale = models.ForeignKey('sales.Sale', on_delete=models.PROTECT, null=True, blank=True, related_name='payments')
    purchase = models.ForeignKey('purchases.Purchase', on_delete=models.PROTECT, null=True, blank=True, related_name='payments')
    customer = models.ForeignKey('customers.Customer', on_delete=models.PROTECT, null=True, blank=True, related_name='payments')
    supplier = models.ForeignKey('suppliers.Supplier', on_delete=models.PROTECT, null=True, blank=True, related_name='payments')
    # Which physical till this cash actually moved through, if any — see
    # CashRegister and finance.services.record_payment's `register` kwarg.
    register = models.ForeignKey('CashRegister', on_delete=models.PROTECT, null=True, blank=True, related_name='payments')

    direction = models.CharField(max_length=3, choices=Direction.choices)
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='payments')
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    date = models.DateField()
    reference = models.CharField(max_length=100, blank=True)
    note = models.CharField(max_length=255, blank=True)

    business_transaction = models.OneToOneField(
        BusinessTransaction, on_delete=models.PROTECT, null=True, blank=True, related_name='payment'
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-id']

    def __str__(self):
        return f"{self.get_direction_display()} {self.amount} via {self.account}"


class Expense(models.Model):
    title = models.CharField(max_length=150)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    date = models.DateField()
    description = models.TextField(blank=True)
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='expenses')
    business_transaction = models.OneToOneField(
        BusinessTransaction, on_delete=models.PROTECT, null=True, blank=True, related_name='expense'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f"{self.title} - {self.amount}"


class Income(models.Model):
    title = models.CharField(max_length=150)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    date = models.DateField()
    description = models.TextField(blank=True)
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='incomes')
    business_transaction = models.OneToOneField(
        BusinessTransaction, on_delete=models.PROTECT, null=True, blank=True, related_name='income'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f"{self.title} - {self.amount}"


class DayClosing(models.Model):
    """A cash-drawer reconciliation for one date. The breakdown fields are a
    snapshot computed and frozen at closing time by finance.services.close_day
    — never edit them directly, and never re-close an already-closed date
    without understanding you're overwriting that snapshot."""
    date = models.DateField(unique=True)
    opening_cash = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    cash_sales = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    customer_cash_payments = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    other_cash_income = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    cash_purchases = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    supplier_cash_payments = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    expenses = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    withdrawals = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    expected_cash = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    actual_cash = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    difference = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f"Day Closing {self.date}"


class CashRegister(models.Model):
    """A physical till/drawer. Its balance is never a field of its own —
    it's a subledger of the chart of accounts, exactly like a Customer/
    Supplier's linked_account, so it can never drift from the GL."""
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20, unique=True)
    warehouse = models.ForeignKey('inventory.Warehouse', on_delete=models.PROTECT, null=True, blank=True, related_name='cash_registers')
    linked_account = models.OneToOneField(Account, on_delete=models.PROTECT, null=True, blank=True, related_name='cash_register')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def current_balance(self):
        # Fresh query, not self.linked_account.balance — see Customer/Supplier
        # current_balance for why (FK-object caching can go stale mid-request).
        return Account.objects.filter(pk=self.linked_account_id).values_list('balance', flat=True).first() or 0


class CashTransaction(models.Model):
    """A manual cash movement in/out of a specific register — opening float,
    a cash drop to the safe, petty-cash withdrawal, or an owner top-up. Sales/
    payments/expenses post to the shared Cash-in-Hand account directly via
    finance.services and are not (yet) tagged to a specific register — this
    is for the register-level manual movements DayClosing doesn't capture."""
    class Type(models.TextChoices):
        OPENING_FLOAT = 'opening_float', 'Opening Float'
        OWNER_FUNDING = 'owner_funding', 'Owner Funding'
        OWNER_WITHDRAWAL = 'owner_withdrawal', 'Owner Withdrawal'
        BANK_TO_REGISTER = 'bank_to_register', 'Bank → Register'
        REGISTER_TO_BANK = 'register_to_bank', 'Register → Bank'
        SAFE_TO_REGISTER = 'safe_to_register', 'Safe → Register'
        REGISTER_TO_SAFE = 'register_to_safe', 'Register → Safe (Cash Drop)'

    class Direction(models.TextChoices):
        IN = 'in', 'In'
        OUT = 'out', 'Out'

    register = models.ForeignKey(CashRegister, on_delete=models.PROTECT, related_name='transactions')
    transaction_type = models.CharField(max_length=20, choices=Type.choices)
    direction = models.CharField(max_length=3, choices=Direction.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    # Snapshot at creation time — append-only row, so this never goes stale.
    balance_after = models.DecimalField(max_digits=14, decimal_places=2, editable=False)
    note = models.CharField(max_length=255, blank=True)
    business_transaction = models.OneToOneField(
        BusinessTransaction, on_delete=models.PROTECT, null=True, blank=True, related_name='cash_transaction'
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.register} {self.get_transaction_type_display()} {self.amount}"
