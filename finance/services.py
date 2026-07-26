from decimal import Decimal

from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from .models import Account, BusinessTransaction, LedgerEntry, Payment, Expense, Income, DayClosing, CashRegister, CashTransaction

# Imported at module level for the sale/purchase overpayment guard in
# record_payment() below — safe: neither sales.models nor purchases.models
# imports finance at module level, so there's no import cycle.
from sales.models import Sale
from purchases.models import Purchase


def _log_payment(user, payment):
    from audit import services as audit_services
    from audit.models import AuditLog
    audit_services.log_action(
        user, AuditLog.Action.PAYMENT, 'finance', payment,
        new_data={'direction': payment.direction, 'amount': str(payment.amount), 'account': payment.account.name},
    )


def post_transaction(date, memo, lines, reference='', created_by=None):
    """Create one balanced BusinessTransaction + its LedgerEntry rows.

    lines: iterable of (account, entry_type, amount). Debits must equal
    credits across all non-zero lines. This is the only place LedgerEntry
    rows and Account.balance updates are created — call it, never write
    those rows directly.
    """
    lines = [(account, entry_type, amount) for account, entry_type, amount in lines if amount]
    debit_total = sum((amt for _, et, amt in lines if et == LedgerEntry.EntryType.DEBIT), Decimal('0'))
    credit_total = sum((amt for _, et, amt in lines if et == LedgerEntry.EntryType.CREDIT), Decimal('0'))
    if debit_total != credit_total:
        raise ValueError(f"Unbalanced transaction: debits {debit_total} != credits {credit_total}")
    if not lines:
        raise ValueError("A transaction needs at least one non-zero line.")

    with transaction.atomic():
        txn = BusinessTransaction.objects.create(date=date, memo=memo, reference=reference, created_by=created_by)
        for account, entry_type, amount in lines:
            LedgerEntry.objects.create(transaction=txn, account=account, entry_type=entry_type, amount=amount)
            _apply_balance_delta(account, entry_type, amount)
    return txn


def _apply_balance_delta(account, entry_type, amount):
    increases = (
        entry_type == LedgerEntry.EntryType.DEBIT
        if account.type in Account.DEBIT_INCREASES
        else entry_type == LedgerEntry.EntryType.CREDIT
    )
    delta = amount if increases else -amount
    Account.objects.filter(pk=account.pk).select_for_update().update(balance=F('balance') + delta)


def get_or_create_party_account(party, account_type, subtype):
    """party is a Customer or Supplier (duck-typed: has .name, .pk, .linked_account)."""
    if party.linked_account_id:
        return party.linked_account
    prefix = 'AR' if subtype == Account.Subtype.AR else 'AP'
    account = Account.objects.create(
        code=f"{prefix}-{party.pk:05d}",
        name=party.name,
        type=account_type,
        subtype=subtype,
    )
    party.linked_account = account
    party.save(update_fields=['linked_account'])
    return account


def get_account(code):
    return Account.objects.get(code=code)


def get_or_create_register_account(register):
    """Same pattern as get_or_create_party_account, but for a CashRegister
    (an ASSET/CASH subledger rather than an AR/AP one)."""
    if register.linked_account_id:
        return register.linked_account
    account = Account.objects.create(
        code=f"REG-{register.pk:05d}", name=f"Cash — {register.name}",
        type=Account.Type.ASSET, subtype=Account.Subtype.CASH,
    )
    register.linked_account = account
    register.save(update_fields=['linked_account'])
    return account


def _signed_party_lines(party_account, counter_account, amount):
    """Build the two ledger lines for moving `amount` against a Customer/
    Supplier's AR/AP account and a counter-account (Equity), where a positive
    `amount` always means "increase the party's balance" in whichever
    direction (debit for AR, credit for AP) that account's normal balance
    grows. Shared by post_opening_balance and post_balance_adjustment so the
    sign convention can't drift between the two."""
    increases_on_debit = party_account.type in Account.DEBIT_INCREASES
    magnitude = abs(amount)
    party_grows = amount > 0
    if party_grows == increases_on_debit:
        return [(party_account, LedgerEntry.EntryType.DEBIT, magnitude), (counter_account, LedgerEntry.EntryType.CREDIT, magnitude)]
    return [(counter_account, LedgerEntry.EntryType.DEBIT, magnitude), (party_account, LedgerEntry.EntryType.CREDIT, magnitude)]


def post_opening_balance(party_account, amount, date, created_by=None):
    """Post a Customer/Supplier opening balance against Opening Balance Equity.
    A positive `amount` always means "increase the party's balance" in whichever
    direction (debit for AR, credit for AP) that account's normal balance grows."""
    if not amount:
        return None
    equity = get_account('3000')
    lines = _signed_party_lines(party_account, equity, amount)
    return post_transaction(date=date, memo='Opening balance', lines=lines, created_by=created_by)


def post_balance_adjustment(party, amount, date, note, created_by=None):
    """The one controlled way to correct a Customer/Supplier balance outside
    the normal sale/purchase/payment flow (e.g. fixing a pre-system data
    error) — see the "Ledger balance ko manually editable na rakho except
    controlled adjustment transaction" requirement. Posts against the same
    Opening Balance Equity account as post_opening_balance and always
    requires a note, since an unexplained adjustment defeats the point of an
    auditable ledger."""
    if not amount:
        raise ValueError("Adjustment amount cannot be zero.")
    if not note:
        raise ValueError("A note explaining the adjustment is required.")
    if not party.linked_account_id:
        raise ValueError("This party has no ledger account yet.")

    equity = get_account('3000')
    lines = _signed_party_lines(party.linked_account, equity, amount)

    with transaction.atomic():
        txn = post_transaction(date=date, memo=f'Balance Adjustment: {note}', lines=lines, created_by=created_by)
        from audit import services as audit_services
        from audit.models import AuditLog
        audit_services.log_action(
            created_by, AuditLog.Action.BALANCE_ADJUSTMENT, 'finance', party,
            new_data={'party': party.name, 'amount': str(amount), 'note': note},
        )
    return txn


LEDGER_KINDS_CUSTOMER = ['Credit Sale', 'Payment Received', 'Payment Given', 'Sales Return', 'Opening Balance', 'Balance Adjustment']
LEDGER_KINDS_SUPPLIER = ['Credit Purchase', 'Payment Made', 'Refund Received', 'Purchase Return', 'Opening Balance', 'Balance Adjustment']


def parse_statement_filters(get_params):
    """GET querydict -> (start, end, kind) for a customer/supplier statement
    view — shared by customers.views and suppliers.views so both stay in
    lockstep with get_party_statement's expected filter shape."""
    return get_params.get('start') or None, get_params.get('end') or None, get_params.get('type') or None


def classify_ledger_entry(entry, party_kind):
    """party_kind: 'customer' or 'supplier'. Returns a short human label for
    one LedgerEntry against a Customer/Supplier's AR/AP account, derived
    entirely from the memo conventions sales/purchases services already use
    plus the Payment (if any) this transaction is linked to — no extra field
    needed, since every ledger-writing call site already leaves an
    unambiguous trail in `memo`."""
    memo = entry.transaction.memo
    if memo == 'Opening balance':
        return 'Opening Balance'
    if memo.startswith('Balance Adjustment'):
        return 'Balance Adjustment'
    if memo.startswith('Sale Invoice #'):
        return 'Credit Sale'
    if memo.startswith('Sales Return'):
        return 'Sales Return'
    if memo.startswith('Purchase Invoice #'):
        return 'Credit Purchase'
    if memo.startswith('Purchase Return'):
        return 'Purchase Return'
    payment = entry.transaction.payment if hasattr(entry.transaction, 'payment') else None
    if payment is not None:
        if party_kind == 'customer':
            return 'Payment Received' if payment.direction == Payment.Direction.IN else 'Payment Given'
        return 'Payment Made' if payment.direction == Payment.Direction.OUT else 'Refund Received'
    return 'Balance Adjustment'


def _entry_delta(entry):
    """Signed effect of one LedgerEntry on its account's balance — same sign
    convention as _apply_balance_delta, but read-only (for computing a
    running balance on a statement without touching Account.balance)."""
    account = entry.account
    increases = (
        entry.entry_type == LedgerEntry.EntryType.DEBIT
        if account.type in Account.DEBIT_INCREASES
        else entry.entry_type == LedgerEntry.EntryType.CREDIT
    )
    return entry.amount if increases else -entry.amount


def get_party_statement(party, party_kind, start=None, end=None, kind=None):
    """party: a Customer or Supplier. party_kind: 'customer' or 'supplier'.

    Returns (entries, summary):
    - entries: LedgerEntry rows against `party.linked_account`, most-recent
      first, each annotated with `.kind` (classify_ledger_entry) and
      `.running_balance`. The running balance always walks every entry in
      the date range regardless of the `kind` filter (seeded from the
      balance as of just before `start`, if given), so filtering by type
      never distorts the running total shown alongside it.
    - summary: dict with total_invoiced, total_paid, outstanding (always
      `party.current_balance` — never independently recomputed, so it can't
      drift from the GL), last_payment, last_transaction.
    """
    empty_summary = {
        'total_invoiced': Decimal('0'), 'total_paid': Decimal('0'),
        'outstanding': party.current_balance, 'last_payment': None, 'last_transaction': None,
    }
    if not party.linked_account_id:
        return [], empty_summary

    base_qs = LedgerEntry.objects.filter(account=party.linked_account).select_related('transaction', 'transaction__payment')

    opening = Decimal('0')
    if start:
        for e in base_qs.filter(transaction__date__lt=start):
            opening += _entry_delta(e)

    qs = base_qs
    if start:
        qs = qs.filter(transaction__date__gte=start)
    if end:
        qs = qs.filter(transaction__date__lte=end)
    qs = qs.order_by('transaction__date', 'id')

    running = opening
    entries = []
    for e in qs:
        e.kind = classify_ledger_entry(e, party_kind)
        running += _entry_delta(e)
        e.running_balance = running
        if kind and e.kind != kind:
            continue
        entries.append(e)
    entries.reverse()

    if party_kind == 'customer':
        total_invoiced = Sale.objects.filter(customer=party).aggregate(t=Sum('total'))['t'] or Decimal('0')
        payments_qs = Payment.objects.filter(customer=party, direction=Payment.Direction.IN)
    else:
        total_invoiced = Purchase.objects.filter(supplier=party).aggregate(t=Sum('total'))['t'] or Decimal('0')
        payments_qs = Payment.objects.filter(supplier=party, direction=Payment.Direction.OUT)

    total_paid = payments_qs.aggregate(t=Sum('amount'))['t'] or Decimal('0')
    last_payment = payments_qs.order_by('-date', '-id').first()
    last_transaction = base_qs.order_by('-transaction__date', '-id').first()

    summary = {
        'total_invoiced': total_invoiced, 'total_paid': total_paid,
        'outstanding': party.current_balance, 'last_payment': last_payment, 'last_transaction': last_transaction,
    }
    return entries, summary


def record_payment(direction, amount, account, date, sale=None, purchase=None,
                    customer=None, supplier=None, note='', reference='', created_by=None, register=None):
    """Record a Payment moving money between a Cash/Bank/Wallet account and a
    customer's/supplier's ledger account, optionally tied to a Sale/Purchase.

    direction=IN means money enters the store's `account` (customer pays us,
    or a supplier refunds us). direction=OUT means money leaves `account`
    (we pay a supplier, or we refund a customer).

    When tied to a specific sale/purchase, direction must match (IN for a
    sale, OUT for a purchase) and amount is capped at that invoice's live
    remaining balance — locked via select_for_update so two concurrent
    payments against the same invoice can't both pass a stale check. On-account
    payments (no sale/purchase) have no such cap — there's no single invoice
    to check against.

    `register`, if given, is which physical till the cash actually moved
    through — it overrides `account` for the GL leg (via
    get_or_create_register_account) so that till's balance stays accurate,
    and is stamped onto the Payment row either way for reporting.
    """
    if amount <= 0:
        raise ValueError("Payment amount must be positive.")

    if register is not None:
        account = get_or_create_register_account(register)

    with transaction.atomic():
        if sale is not None:
            if direction != Payment.Direction.IN:
                raise ValueError(f"Sale #{sale.invoice_no} can only take an incoming payment.")
            locked_sale = Sale.objects.select_for_update().get(pk=sale.pk)
            if amount > locked_sale.remaining:
                raise ValueError(f"Cannot record {amount}: only {locked_sale.remaining} remaining on Sale #{sale.invoice_no}.")
        if purchase is not None:
            if direction != Payment.Direction.OUT:
                raise ValueError(f"Purchase #{purchase.invoice_no} can only take an outgoing payment.")
            locked_purchase = Purchase.objects.select_for_update().get(pk=purchase.pk)
            if amount > locked_purchase.remaining:
                raise ValueError(f"Cannot record {amount}: only {locked_purchase.remaining} remaining on Purchase #{purchase.invoice_no}.")

        customer = customer or (sale.customer if sale else None)
        supplier = supplier or (purchase.supplier if purchase else None)

        if customer is not None:
            party_account = get_or_create_party_account(customer, Account.Type.ASSET, Account.Subtype.AR)
        elif supplier is not None:
            party_account = get_or_create_party_account(supplier, Account.Type.LIABILITY, Account.Subtype.AP)
        else:
            raise ValueError("A payment must be linked to a customer or a supplier.")

        memo_bits = [b for b in [
            f"Sale #{sale.invoice_no}" if sale else None,
            f"Purchase #{purchase.invoice_no}" if purchase else None,
        ] if b]
        memo = note or (' / '.join(memo_bits) or 'Payment')

        if direction == Payment.Direction.IN:
            lines = [(account, LedgerEntry.EntryType.DEBIT, amount), (party_account, LedgerEntry.EntryType.CREDIT, amount)]
        else:
            lines = [(party_account, LedgerEntry.EntryType.DEBIT, amount), (account, LedgerEntry.EntryType.CREDIT, amount)]

        txn = post_transaction(date=date, memo=memo, lines=lines, reference=reference, created_by=created_by)
        payment = Payment.objects.create(
            sale=sale, purchase=purchase, customer=customer, supplier=supplier,
            direction=direction, account=account, amount=amount, date=date,
            reference=reference, note=note, business_transaction=txn, created_by=created_by,
            register=register,
        )
        _log_payment(created_by, payment)
    return payment


def post_expense(expense, created_by=None):
    operating_expenses = get_account('5100')
    with transaction.atomic():
        txn = post_transaction(
            date=expense.date,
            memo=f"Expense: {expense.title}",
            lines=[
                (operating_expenses, LedgerEntry.EntryType.DEBIT, expense.amount),
                (expense.account, LedgerEntry.EntryType.CREDIT, expense.amount),
            ],
            created_by=created_by,
        )
        expense.business_transaction = txn
        expense.save(update_fields=['business_transaction'])
    return txn


def post_income(income, created_by=None):
    other_income = get_account('4100')
    with transaction.atomic():
        txn = post_transaction(
            date=income.date,
            memo=f"Income: {income.title}",
            lines=[
                (income.account, LedgerEntry.EntryType.DEBIT, income.amount),
                (other_income, LedgerEntry.EntryType.CREDIT, income.amount),
            ],
            created_by=created_by,
        )
        income.business_transaction = txn
        income.save(update_fields=['business_transaction'])
    return txn


def close_day(date, opening_cash, actual_cash, withdrawals, note, user):
    """Compute and freeze a cash-drawer reconciliation snapshot for `date`.

    "Cash Sales" = walk-in (no-customer) sale totals, which are always fully
    cash, plus any Payment tied directly to a Sale. "Customer Cash Payments"
    is cash received against a customer's overall balance with no specific
    Sale attached (an on-account payment). Purchases mirror the same split
    against Supplier. Re-closing an already-closed date overwrites its
    snapshot — the caller should treat that as a correction, not routine use.
    """
    from sales.models import Sale  # local import: finance must not depend on sales at module load time

    cash_account = get_account('1000')

    walkin_sales = Sale.objects.filter(customer__isnull=True, date=date).aggregate(t=Sum('total'))['t'] or Decimal('0')
    sale_cash_payments = Payment.objects.filter(
        direction=Payment.Direction.IN, account=cash_account, sale__isnull=False, date=date,
    ).aggregate(t=Sum('amount'))['t'] or Decimal('0')
    cash_sales = walkin_sales + sale_cash_payments

    customer_cash_payments = Payment.objects.filter(
        direction=Payment.Direction.IN, account=cash_account, sale__isnull=True, customer__isnull=False, date=date,
    ).aggregate(t=Sum('amount'))['t'] or Decimal('0')

    other_cash_income = Income.objects.filter(account=cash_account, date=date).aggregate(t=Sum('amount'))['t'] or Decimal('0')

    cash_purchases = Payment.objects.filter(
        direction=Payment.Direction.OUT, account=cash_account, purchase__isnull=False, date=date,
    ).aggregate(t=Sum('amount'))['t'] or Decimal('0')
    supplier_cash_payments = Payment.objects.filter(
        direction=Payment.Direction.OUT, account=cash_account, purchase__isnull=True, supplier__isnull=False, date=date,
    ).aggregate(t=Sum('amount'))['t'] or Decimal('0')

    expenses = Expense.objects.filter(account=cash_account, date=date).aggregate(t=Sum('amount'))['t'] or Decimal('0')

    expected_cash = (
        opening_cash + cash_sales + customer_cash_payments + other_cash_income
        - cash_purchases - supplier_cash_payments - expenses - withdrawals
    )
    difference = actual_cash - expected_cash

    with transaction.atomic():
        closing, _ = DayClosing.objects.update_or_create(
            date=date,
            defaults=dict(
                opening_cash=opening_cash, cash_sales=cash_sales, customer_cash_payments=customer_cash_payments,
                other_cash_income=other_cash_income, cash_purchases=cash_purchases,
                supplier_cash_payments=supplier_cash_payments, expenses=expenses, withdrawals=withdrawals,
                expected_cash=expected_cash, actual_cash=actual_cash, difference=difference,
                note=note, created_by=user,
            ),
        )
        if withdrawals:
            drawings_account, _ = Account.objects.get_or_create(
                code='3100', defaults={'name': "Owner's Drawings", 'type': Account.Type.EQUITY}
            )
            post_transaction(
                date=date, memo=f'Cash withdrawal — Day Closing {date}',
                lines=[
                    (drawings_account, LedgerEntry.EntryType.DEBIT, withdrawals),
                    (cash_account, LedgerEntry.EntryType.CREDIT, withdrawals),
                ],
                created_by=user,
            )

        from audit import services as audit_services
        from audit.models import AuditLog
        audit_services.log_action(
            user, AuditLog.Action.DAY_CLOSING, 'finance', closing,
            new_data={'date': str(date), 'expected_cash': str(expected_cash), 'actual_cash': str(actual_cash), 'difference': str(difference)},
        )
    return closing


COUNTER_ACCOUNT_BY_TYPE = {
    CashTransaction.Type.OPENING_FLOAT: '3200',
    CashTransaction.Type.OWNER_FUNDING: '3200',
    CashTransaction.Type.OWNER_WITHDRAWAL: '3200',
    CashTransaction.Type.BANK_TO_REGISTER: '1010',
    CashTransaction.Type.REGISTER_TO_BANK: '1010',
    CashTransaction.Type.SAFE_TO_REGISTER: '1005',
    CashTransaction.Type.REGISTER_TO_SAFE: '1005',
}


def record_cash_transaction(register, transaction_type, direction, amount, note, user):
    """Manual cash movement in/out of a register (opening float, owner
    funding/withdrawal, or a transfer to/from the bank or safe). The GL
    counter-account depends on transaction_type (see COUNTER_ACCOUNT_BY_TYPE)
    so e.g. a cash drop to the safe posts against Cash in Safe, not Owner
    Capital — the register's balance is always derivable from real
    LedgerEntry rows against the correct counter-account, never a hand-set
    number or a misattributed equity movement."""
    if amount <= 0:
        raise ValueError("Amount must be positive.")

    counter_account = get_account(COUNTER_ACCOUNT_BY_TYPE[transaction_type])
    register_account = register.linked_account

    if direction == CashTransaction.Direction.IN:
        lines = [
            (register_account, LedgerEntry.EntryType.DEBIT, amount),
            (counter_account, LedgerEntry.EntryType.CREDIT, amount),
        ]
    else:
        lines = [
            (counter_account, LedgerEntry.EntryType.DEBIT, amount),
            (register_account, LedgerEntry.EntryType.CREDIT, amount),
        ]

    with transaction.atomic():
        txn = post_transaction(
            date=timezone.localdate(), memo=f'{CashTransaction.Type(transaction_type).label} — {register.name}',
            lines=lines, created_by=user,
        )
        balance_after = Account.objects.get(pk=register_account.pk).balance
        cash_txn = CashTransaction.objects.create(
            register=register, transaction_type=transaction_type, direction=direction, amount=amount,
            balance_after=balance_after, note=note, business_transaction=txn, created_by=user,
        )

        from audit import services as audit_services
        from audit.models import AuditLog
        audit_services.log_action(
            user, AuditLog.Action.CASH_REGISTER_TRANSACTION, 'finance', cash_txn,
            new_data={'register': register.name, 'type': transaction_type, 'direction': direction, 'amount': str(amount)},
        )
    return cash_txn
