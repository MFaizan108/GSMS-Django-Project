from decimal import Decimal
from datetime import datetime, timedelta

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db.models import Sum, F, Q

from products.models import Product
from customers.models import Customer
from suppliers.models import Supplier
from sales.models import Sale, SaleItem
from purchases.models import Purchase
from finance.models import Account, Expense, Income, LedgerEntry, Payment
from notifications import services as notifications_services

TREND_DAYS = 14


@login_required
def index(request):
    notifications_services.refresh_notifications()
    today = timezone.localdate()

    date_str = request.GET.get('date')
    selected_date = today
    if date_str:
        try:
            parsed = datetime.strptime(date_str, '%Y-%m-%d').date()
            if parsed <= today:
                selected_date = parsed
        except ValueError:
            pass

    todays_sales_qs = Sale.objects.filter(date=selected_date)
    todays_purchases_qs = Purchase.objects.filter(date=selected_date)

    todays_sales_total = todays_sales_qs.aggregate(t=Sum('total'))['t'] or 0
    todays_purchases_total = todays_purchases_qs.aggregate(t=Sum('total'))['t'] or 0
    todays_credit_sales = todays_sales_qs.filter(payment_type='credit').aggregate(t=Sum('total'))['t'] or 0
    todays_cash_received = todays_sales_qs.aggregate(t=Sum('paid'))['t'] or 0
    todays_expenses = Expense.objects.filter(date=selected_date).aggregate(t=Sum('amount'))['t'] or 0
    todays_income = Income.objects.filter(date=selected_date).aggregate(t=Sum('amount'))['t'] or 0

    todays_profit = 0
    for sale in todays_sales_qs.prefetch_related('items'):
        todays_profit += sale.total_profit

    cash_in_hand = todays_cash_received + todays_income - todays_expenses

    products = Product.objects.filter(status=Product.Status.ACTIVE)
    low_stock = [p for p in products if p.is_low_stock]
    expired = [p for p in products if p.is_expired]
    near_expiry = [p for p in products if p.is_near_expiry]

    trend_start = selected_date - timedelta(days=TREND_DAYS - 1)
    sales_by_date = dict(
        Sale.objects.filter(date__gte=trend_start, date__lte=selected_date)
        .values('date').annotate(t=Sum('total')).values_list('date', 't')
    )
    purchases_by_date = dict(
        Purchase.objects.filter(date__gte=trend_start, date__lte=selected_date)
        .values('date').annotate(t=Sum('total')).values_list('date', 't')
    )
    trend_labels, trend_sales, trend_purchases = [], [], []
    d = trend_start
    while d <= selected_date:
        trend_labels.append(d.strftime('%d %b'))
        trend_sales.append(float(sales_by_date.get(d, 0)))
        trend_purchases.append(float(purchases_by_date.get(d, 0)))
        d += timedelta(days=1)

    top_products_qs = (
        SaleItem.objects.filter(sale__date__gte=trend_start, sale__date__lte=selected_date)
        .values('product__name')
        .annotate(revenue=Sum(F('quantity') * F('selling_price')))
        .order_by('-revenue')[:5]
    )
    top_products_labels = [row['product__name'] for row in top_products_qs]
    top_products_data = [float(row['revenue'] or 0) for row in top_products_qs]

    total_receivables = Account.objects.filter(
        subtype=Account.Subtype.AR, balance__gt=0,
    ).aggregate(t=Sum('balance'))['t'] or Decimal('0')
    total_payables = Account.objects.filter(
        subtype=Account.Subtype.AP, balance__gt=0,
    ).aggregate(t=Sum('balance'))['t'] or Decimal('0')
    net_outstanding = total_receivables - total_payables

    top_customers_by_outstanding = (
        Customer.objects.filter(linked_account__balance__gt=0)
        .select_related('linked_account').order_by('-linked_account__balance')[:5]
    )
    top_suppliers_by_payable = (
        Supplier.objects.filter(linked_account__balance__gt=0)
        .select_related('linked_account').order_by('-linked_account__balance')[:5]
    )

    recent_credit_transactions = (
        LedgerEntry.objects.filter(Q(transaction__memo__startswith='Sale Invoice #') | Q(transaction__memo__startswith='Purchase Invoice #'))
        .select_related('transaction', 'account').order_by('-transaction__date', '-id')[:8]
    )
    recent_payments = Payment.objects.select_related('customer', 'supplier', 'account').order_by('-date', '-id')[:8]

    context = {
        'trend_labels': trend_labels,
        'trend_sales': trend_sales,
        'trend_purchases': trend_purchases,
        'top_products_labels': top_products_labels,
        'top_products_data': top_products_data,
        'today': today,
        'selected_date': selected_date,
        'is_today': selected_date == today,
        'todays_sales_total': todays_sales_total,
        'todays_purchases_total': todays_purchases_total,
        'todays_profit': todays_profit,
        'todays_credit_sales': todays_credit_sales,
        'cash_in_hand': cash_in_hand,
        'total_customers': Customer.objects.count(),
        'total_suppliers': Supplier.objects.count(),
        'total_products': Product.objects.count(),
        'low_stock_products': low_stock,
        'expired_products': expired,
        'near_expiry_products': near_expiry,
        'recent_sales': todays_sales_qs.select_related('customer').order_by('-id')[:8],
        'recent_purchases': todays_purchases_qs.select_related('supplier').order_by('-id')[:8],
        'total_receivables': total_receivables,
        'total_payables': total_payables,
        'net_outstanding': net_outstanding,
        'top_customers_by_outstanding': top_customers_by_outstanding,
        'top_suppliers_by_payable': top_suppliers_by_payable,
        'recent_credit_transactions': recent_credit_transactions,
        'recent_payments': recent_payments,
    }
    return render(request, 'dashboard/index.html', context)
