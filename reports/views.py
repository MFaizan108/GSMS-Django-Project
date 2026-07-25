from decimal import Decimal

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, F, Q, DecimalField, ExpressionWrapper
from django.utils import timezone

from accounts.decorators import manager_required
from sales.models import Sale, SaleItem
from purchases.models import Purchase
from products.models import Product
from customers.models import Customer
from suppliers.models import Supplier
from finance.models import Account, Expense, LedgerEntry, Payment
from finance import services as finance_services
from inventory.models import InventoryTransaction, ProductBatch, BatchStock


def _date_range(request):
    today = timezone.localdate()
    start = request.GET.get('start') or str(today.replace(day=1))
    end = request.GET.get('end') or str(today)
    return start, end


@login_required
def index(request):
    return render(request, 'reports/index.html')


@login_required
def sales_report(request):
    start, end = _date_range(request)
    sales = Sale.objects.filter(date__gte=start, date__lte=end).select_related('customer')
    total = sales.aggregate(t=Sum('total'))['t'] or 0
    profit = sum((s.total_profit for s in sales), start=0)
    return render(request, 'reports/sales_report.html', {
        'sales': sales, 'total': total, 'profit': profit, 'start': start, 'end': end,
    })


@login_required
def purchase_report(request):
    start, end = _date_range(request)
    purchases = Purchase.objects.filter(date__gte=start, date__lte=end).select_related('supplier')
    total = purchases.aggregate(t=Sum('total'))['t'] or 0
    return render(request, 'reports/purchase_report.html', {
        'purchases': purchases, 'total': total, 'start': start, 'end': end,
    })


@manager_required
def profit_report(request):
    start, end = _date_range(request)
    sales = Sale.objects.filter(date__gte=start, date__lte=end).prefetch_related('items')
    total_sales = sales.aggregate(t=Sum('total'))['t'] or 0
    total_profit = sum((s.total_profit for s in sales), start=0)
    total_expenses = Expense.objects.filter(date__gte=start, date__lte=end).aggregate(t=Sum('amount'))['t'] or 0
    net_profit = total_profit - total_expenses
    return render(request, 'reports/profit_report.html', {
        'total_sales': total_sales, 'total_profit': total_profit,
        'total_expenses': total_expenses, 'net_profit': net_profit,
        'start': start, 'end': end,
    })


@manager_required
def expense_report(request):
    start, end = _date_range(request)
    expenses = Expense.objects.filter(date__gte=start, date__lte=end)
    total = expenses.aggregate(t=Sum('amount'))['t'] or 0
    return render(request, 'reports/expense_report.html', {'expenses': expenses, 'total': total, 'start': start, 'end': end})


@login_required
def stock_report(request):
    products = Product.objects.select_related('category', 'unit').all()
    return render(request, 'reports/stock_report.html', {'products': products})


@login_required
def expiry_report(request):
    """Reads from ProductBatch/BatchStock, not Product.expiry_date — a
    product's single expiry_date field only ever holds the most recent
    purchase's expiry (see purchases.services.create_purchase), so a product
    with several batches on different expiry dates would silently drop all
    but the newest one under the old approach. Also surfaces which warehouse
    the expiring stock is physically in, now that stock is warehouse-scoped."""
    today = timezone.localdate()
    stocks = (
        BatchStock.objects.filter(batch__expiry_date__isnull=False, quantity__gt=0)
        .select_related('batch__product', 'warehouse')
        .order_by('batch__expiry_date')
    )
    rows = []
    for bs in stocks:
        days = (bs.batch.expiry_date - today).days
        if days < 0:
            bucket = 'Expired'
        elif days <= 7:
            bucket = '7 Days'
        elif days <= 15:
            bucket = '15 Days'
        elif days <= 30:
            bucket = '30 Days'
        else:
            bucket = 'Later'
        rows.append({
            'product': bs.batch.product, 'batch': bs.batch, 'warehouse': bs.warehouse,
            'quantity': bs.quantity, 'expiry_date': bs.batch.expiry_date, 'days': days, 'bucket': bucket,
        })
    return render(request, 'reports/expiry_report.html', {'rows': rows, 'today': today})


@login_required
def low_stock_report(request):
    products = [p for p in Product.objects.all() if p.is_low_stock]
    return render(request, 'reports/low_stock_report.html', {'products': products})


@login_required
def top_selling_report(request):
    items = (
        SaleItem.objects.values('product__name')
        .annotate(total_qty=Sum('quantity'), total_revenue=Sum(
            ExpressionWrapper(F('quantity') * F('selling_price'), output_field=DecimalField())
        ))
        .order_by('-total_qty')[:20]
    )
    return render(request, 'reports/top_selling_report.html', {'items': items})


@login_required
def customer_balance_report(request):
    customers = Customer.objects.filter(linked_account__balance__gt=0).select_related('linked_account').order_by('-linked_account__balance')
    total = customers.aggregate(t=Sum('linked_account__balance'))['t'] or 0
    return render(request, 'reports/customer_balance_report.html', {'customers': customers, 'total': total})


@login_required
def payment_collection_report(request):
    """Every incoming payment received from a customer — date, customer,
    amount — including baqaya (due) collected against an existing invoice
    and on-account payments. Answers "which customer paid how much on which
    day", which the balance-only customer_balance_report doesn't."""
    start, end = _date_range(request)
    payments = Payment.objects.filter(
        direction=Payment.Direction.IN, customer__isnull=False, date__gte=start, date__lte=end,
    ).select_related('customer', 'account', 'sale').order_by('-date', '-id')
    total = payments.aggregate(t=Sum('amount'))['t'] or 0
    return render(request, 'reports/payment_collection_report.html', {
        'payments': payments, 'total': total, 'start': start, 'end': end,
    })


@login_required
def supplier_balance_report(request):
    suppliers = Supplier.objects.filter(linked_account__balance__gt=0).select_related('linked_account').order_by('-linked_account__balance')
    total = suppliers.aggregate(t=Sum('linked_account__balance'))['t'] or 0
    return render(request, 'reports/supplier_balance_report.html', {'suppliers': suppliers, 'total': total})


@login_required
def least_selling_report(request):
    items = (
        SaleItem.objects.values('product__name')
        .annotate(total_qty=Sum('quantity'), total_revenue=Sum(
            ExpressionWrapper(F('quantity') * F('selling_price'), output_field=DecimalField())
        ))
        .order_by('total_qty')[:20]
    )
    return render(request, 'reports/least_selling_report.html', {'items': items})


@manager_required
def stock_movement_report(request):
    start, end = _date_range(request)
    transactions = (
        InventoryTransaction.objects.filter(date__date__gte=start, date__date__lte=end)
        .select_related('product', 'warehouse', 'batch')
        .order_by('-date')[:500]
    )
    return render(request, 'reports/stock_movement_report.html', {'transactions': transactions, 'start': start, 'end': end})


@manager_required
def inventory_valuation_report(request):
    rows = (
        ProductBatch.objects.filter(remaining_quantity__gt=0)
        .values('product__name')
        .annotate(
            qty=Sum('remaining_quantity'),
            value=Sum(ExpressionWrapper(F('remaining_quantity') * F('unit_cost'), output_field=DecimalField())),
        )
        .order_by('-value')
    )
    total_value = sum((r['value'] or 0 for r in rows), Decimal('0'))
    return render(request, 'reports/inventory_valuation_report.html', {'rows': rows, 'total_value': total_value})


@manager_required
def abc_analysis_report(request):
    start, end = _date_range(request)
    rows = list(
        SaleItem.objects.filter(sale__date__gte=start, sale__date__lte=end)
        .values('product__name')
        .annotate(revenue=Sum(ExpressionWrapper(F('quantity') * F('selling_price'), output_field=DecimalField())))
        .order_by('-revenue')
    )
    total_revenue = sum((r['revenue'] or 0 for r in rows), Decimal('0'))
    cumulative = Decimal('0')
    for r in rows:
        cumulative += r['revenue'] or 0
        pct = (cumulative / total_revenue * 100) if total_revenue else Decimal('0')
        r['cumulative_pct'] = pct
        if pct <= 80:
            r['klass'] = 'A'
        elif pct <= 95:
            r['klass'] = 'B'
        else:
            r['klass'] = 'C'
    return render(request, 'reports/abc_analysis_report.html', {'rows': rows, 'total_revenue': total_revenue, 'start': start, 'end': end})


@manager_required
def dead_stock_report(request):
    days = int(request.GET.get('days', 60))
    cutoff = timezone.localdate() - timezone.timedelta(days=days)
    recently_sold_ids = SaleItem.objects.filter(sale__date__gte=cutoff).values_list('product_id', flat=True).distinct()
    products = Product.objects.filter(stock__gt=0).exclude(pk__in=recently_sold_ids).select_related('category', 'unit')
    return render(request, 'reports/dead_stock_report.html', {'products': products, 'days': days})


@manager_required
def cash_flow_report(request):
    """Derived from the GL, not from Sale.paid/Purchase.paid — those are
    cached cumulative-to-date totals on the invoice row, keyed by invoice
    date, not by when cash actually moved. A January credit sale paid off
    today would misreport as January's cash flow under that approach. This
    instead sums LedgerEntry rows against real cash/bank/wallet accounts
    (Account.PAYMENT_SUBTYPES), filtered by the actual transaction date —
    which for a Payment is the date cash changed hands. Summing debits/credits
    across all such accounts together also means an internal transfer between
    two cash accounts (e.g. a cash-register deposit to the bank) nets to zero,
    exactly as a real cash-flow statement should treat it."""
    start, end = _date_range(request)
    entries = LedgerEntry.objects.filter(
        account__subtype__in=Account.PAYMENT_SUBTYPES,
        transaction__date__gte=start, transaction__date__lte=end,
    )
    cash_in = entries.filter(entry_type=LedgerEntry.EntryType.DEBIT).aggregate(t=Sum('amount'))['t'] or Decimal('0')
    cash_out = entries.filter(entry_type=LedgerEntry.EntryType.CREDIT).aggregate(t=Sum('amount'))['t'] or Decimal('0')
    net_cash = cash_in - cash_out

    by_account = (
        entries.values('account__code', 'account__name')
        .annotate(
            debit=Sum('amount', filter=Q(entry_type=LedgerEntry.EntryType.DEBIT)),
            credit=Sum('amount', filter=Q(entry_type=LedgerEntry.EntryType.CREDIT)),
        )
        .order_by('account__code')
    )
    for row in by_account:
        row['net'] = (row['debit'] or Decimal('0')) - (row['credit'] or Decimal('0'))

    return render(request, 'reports/cash_flow_report.html', {
        'cash_in': cash_in, 'cash_out': cash_out, 'net_cash': net_cash,
        'by_account': by_account, 'start': start, 'end': end,
    })


@manager_required
def account_reconciliation_report(request):
    """Account.balance is a cache maintained incrementally by
    finance.services.post_transaction (see _apply_balance_delta) — this
    report independently recomputes each account's balance from the raw,
    append-only LedgerEntry rows and flags any account where the two
    disagree, so a bug in the caching path (or any row inserted outside
    post_transaction) surfaces instead of silently drifting forever."""
    rows = []
    for account in Account.objects.order_by('code'):
        debit_total = account.entries.filter(entry_type=LedgerEntry.EntryType.DEBIT).aggregate(t=Sum('amount'))['t'] or Decimal('0')
        credit_total = account.entries.filter(entry_type=LedgerEntry.EntryType.CREDIT).aggregate(t=Sum('amount'))['t'] or Decimal('0')
        if account.type in Account.DEBIT_INCREASES:
            computed_balance = debit_total - credit_total
        else:
            computed_balance = credit_total - debit_total
        difference = account.balance - computed_balance
        rows.append({
            'account': account, 'debit_total': debit_total, 'credit_total': credit_total,
            'computed_balance': computed_balance, 'difference': difference,
        })
    mismatches = [r for r in rows if r['difference']]
    return render(request, 'reports/account_reconciliation_report.html', {'rows': rows, 'mismatches': mismatches})


def _udhaar_status(balance):
    if balance > 0:
        return 'Outstanding'
    if balance < 0:
        return 'Advance'
    return 'Fully Paid'


@login_required
def udhaar_home(request):
    """The dedicated Udhaar/Ledger hub: Customer Receivables + Supplier
    Payables side by side (each row's outstanding is always party.current_balance
    — the same live GL query customer/supplier detail pages use, never
    independently recomputed) plus a combined recent-activity feed across
    both, which is where the date-range/transaction-type filters concretely
    apply since they don't map cleanly onto a balance-summary row."""
    status_filter = request.GET.get('status', 'all')
    q = request.GET.get('q', '').strip()

    customers = Customer.objects.all()
    if q:
        customers = customers.filter(name__icontains=q)
    customer_rows = []
    for c in customers:
        balance = c.current_balance
        row_status = _udhaar_status(balance)
        if status_filter == 'outstanding' and row_status != 'Outstanding':
            continue
        if status_filter == 'fully_paid' and row_status != 'Fully Paid':
            continue
        customer_rows.append({
            'party': c,
            'total_credit': Sale.objects.filter(customer=c).aggregate(t=Sum('total'))['t'] or Decimal('0'),
            'total_paid': Payment.objects.filter(customer=c, direction=Payment.Direction.IN).aggregate(t=Sum('amount'))['t'] or Decimal('0'),
            'outstanding': balance,
            'last_transaction': c.ledger_entries.first(),
            'status': row_status,
        })

    suppliers = Supplier.objects.all()
    if q:
        suppliers = suppliers.filter(name__icontains=q)
    supplier_rows = []
    for s in suppliers:
        balance = s.current_balance
        row_status = _udhaar_status(balance)
        if status_filter == 'outstanding' and row_status != 'Outstanding':
            continue
        if status_filter == 'fully_paid' and row_status != 'Fully Paid':
            continue
        supplier_rows.append({
            'party': s,
            'total_credit': Purchase.objects.filter(supplier=s).aggregate(t=Sum('total'))['t'] or Decimal('0'),
            'total_paid': Payment.objects.filter(supplier=s, direction=Payment.Direction.OUT).aggregate(t=Sum('amount'))['t'] or Decimal('0'),
            'outstanding': balance,
            'last_transaction': s.ledger_entries.first(),
            'status': row_status,
        })

    total_receivables = sum((r['outstanding'] for r in customer_rows if r['outstanding'] > 0), Decimal('0'))
    total_payables = sum((r['outstanding'] for r in supplier_rows if r['outstanding'] > 0), Decimal('0'))

    # Recent ledger activity, combined across both parties.
    act_start = request.GET.get('start') or None
    act_end = request.GET.get('end') or None
    act_party_type = request.GET.get('party_type', '')
    act_type = request.GET.get('activity_type', '')

    customers_with_account = list(Customer.objects.exclude(linked_account__isnull=True))
    suppliers_with_account = list(Supplier.objects.exclude(linked_account__isnull=True))
    account_to_customer = {c.linked_account_id: c for c in customers_with_account}
    account_to_supplier = {s.linked_account_id: s for s in suppliers_with_account}

    if act_party_type == 'customer':
        account_ids = list(account_to_customer.keys())
    elif act_party_type == 'supplier':
        account_ids = list(account_to_supplier.keys())
    else:
        account_ids = list(account_to_customer.keys()) + list(account_to_supplier.keys())

    activity_qs = LedgerEntry.objects.filter(account_id__in=account_ids).select_related('transaction', 'transaction__payment')
    if act_start:
        activity_qs = activity_qs.filter(transaction__date__gte=act_start)
    if act_end:
        activity_qs = activity_qs.filter(transaction__date__lte=act_end)
    activity_qs = activity_qs.order_by('-transaction__date', '-id')[:50]

    activity_rows = []
    for e in activity_qs:
        if e.account_id in account_to_customer:
            party, party_kind = account_to_customer[e.account_id], 'customer'
        else:
            party, party_kind = account_to_supplier.get(e.account_id), 'supplier'
        kind = finance_services.classify_ledger_entry(e, party_kind)
        if act_type and kind != act_type:
            continue
        activity_rows.append({'entry': e, 'party': party, 'party_kind': party_kind, 'kind': kind})

    return render(request, 'reports/udhaar_home.html', {
        'customer_rows': customer_rows, 'supplier_rows': supplier_rows,
        'total_receivables': total_receivables, 'total_payables': total_payables,
        'net_outstanding': total_receivables - total_payables,
        'activity_rows': activity_rows,
        'status_filter': status_filter, 'q': q,
        'start': act_start or '', 'end': act_end or '', 'party_type': act_party_type, 'activity_type': act_type,
        'kind_choices': sorted(set(finance_services.LEDGER_KINDS_CUSTOMER + finance_services.LEDGER_KINDS_SUPPLIER)),
    })
