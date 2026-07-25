from decimal import Decimal, InvalidOperation

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import ProtectedError
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.views.decorators.http import require_POST
from accounts.decorators import manager_required
from core.pdf import render_to_pdf
from finance import services as finance_services
from finance.models import Account, Payment, CashRegister
from payments import services as payments_services
from sales.models import Sale
from settings_app.models import StoreSettings
from .models import Customer
from .forms import CustomerForm, CustomerPaymentForm, BalanceAdjustmentForm


@login_required
def customer_list(request):
    customers = Customer.objects.all()
    return render(request, 'customers/customer_list.html', {'customers': customers})


@login_required
def customer_detail(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    start, end, kind = finance_services.parse_statement_filters(request.GET)
    ledger, stats = finance_services.get_party_statement(customer, 'customer', start=start, end=end, kind=kind)
    payment_form = CustomerPaymentForm(auto_id='id_recv_%s')
    give_payment_form = CustomerPaymentForm(auto_id='id_give_%s')
    adjustment_form = BalanceAdjustmentForm()
    return render(request, 'customers/customer_detail.html', {
        'customer': customer, 'ledger': ledger[:200], 'stats': stats,
        'payment_form': payment_form, 'give_payment_form': give_payment_form, 'adjustment_form': adjustment_form,
        'start': start or '', 'end': end or '', 'selected_kind': kind or '', 'kind_choices': finance_services.LEDGER_KINDS_CUSTOMER,
    })


@login_required
def customer_statement_pdf(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    start, end, kind = finance_services.parse_statement_filters(request.GET)
    ledger, stats = finance_services.get_party_statement(customer, 'customer', start=start, end=end, kind=kind)
    pdf_bytes = render_to_pdf('customers/customer_statement_pdf.html', {
        'customer': customer, 'ledger': ledger, 'stats': stats, 'start': start, 'end': end,
        'store_settings': StoreSettings.get_solo(),
    })
    if pdf_bytes is None:
        messages.error(request, 'Could not generate the statement PDF.')
        return redirect('customers:customer_detail', pk=pk)
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="statement-{customer.name}.pdf"'
    return response


@manager_required
def customer_balance_adjustment(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    if request.method == 'POST':
        form = BalanceAdjustmentForm(request.POST)
        if form.is_valid():
            try:
                finance_services.post_balance_adjustment(
                    customer, form.cleaned_data['amount'], timezone.localdate(),
                    form.cleaned_data['note'], created_by=request.user,
                )
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, 'Balance adjustment recorded.')
        else:
            messages.error(request, 'Could not record adjustment — check the amount and note.')
    return redirect('customers:customer_detail', pk=pk)


@login_required
def customer_create(request):
    if request.method == 'POST':
        form = CustomerForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                customer = form.save()
                finance_services.get_or_create_party_account(customer, Account.Type.ASSET, Account.Subtype.AR)
                finance_services.post_opening_balance(
                    customer.linked_account, customer.opening_balance, timezone.localdate(), created_by=request.user,
                )
            messages.success(request, 'Customer added.')
            return redirect('customers:customer_list')
    else:
        form = CustomerForm()
    return render(request, 'customers/customer_form.html', {'form': form, 'title': 'Add Customer'})


@manager_required
def customer_edit(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    if request.method == 'POST':
        form = CustomerForm(request.POST, instance=customer)
        if form.is_valid():
            form.save()
            messages.success(request, 'Customer updated.')
            return redirect('customers:customer_list')
    else:
        form = CustomerForm(instance=customer)
    return render(request, 'customers/customer_form.html', {'form': form, 'title': 'Edit Customer'})


@manager_required
@require_POST
def customer_delete(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    try:
        customer.delete()
        messages.success(request, 'Customer deleted.')
    except ProtectedError:
        messages.error(request, f'Cannot delete {customer.name} — this customer has existing sales records.')
    return redirect('customers:customer_list')


def _cash_account():
    return finance_services.get_account('1000')


def _collect_due(customer, amount, account, date, note, created_by):
    """Pay off the customer's oldest outstanding sale(s) first (FIFO) so the
    money actually shows up on the bill(s) it settled — a plain unallocated
    on-account credit was invisible on every invoice, which is exactly what
    was confusing cashiers collecting baqaya from the New Sale screen or the
    customer page. Any amount left over after every due invoice is covered
    (a genuine advance) still lands as a plain on-account Payment. `account`
    should already be resolved (register's account or the default cash
    account) — both the allocated and leftover portions use the same one."""
    outstanding = list(Sale.objects.filter(customer=customer, remaining__gt=0).order_by('date', 'id'))
    remaining_amount = amount
    allocations = []
    for sale in outstanding:
        if remaining_amount <= 0:
            break
        take = min(remaining_amount, sale.remaining)
        allocations.append((sale, take))
        remaining_amount -= take

    if allocations:
        payments_services.allocate_payment(
            Payment.Direction.IN, account, date, allocations, customer=customer, note=note, created_by=created_by,
        )
    if remaining_amount > 0:
        finance_services.record_payment(
            Payment.Direction.IN, remaining_amount, account, date,
            customer=customer, note=note, created_by=created_by,
        )


@login_required
def customer_payment(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    if request.method == 'POST':
        form = CustomerPaymentForm(request.POST)
        if form.is_valid():
            amount = form.cleaned_data['amount']
            desc = form.cleaned_data['description'] or 'Payment received from customer'
            register = form.cleaned_data.get('register')
            account = finance_services.get_or_create_register_account(register) if register else _cash_account()
            try:
                _collect_due(customer, amount, account, timezone.localdate(), desc, request.user)
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, f'Payment of {amount} recorded.')
        else:
            messages.error(request, 'Could not record payment — check the amount.')
    return redirect('customers:customer_detail', pk=pk)


@manager_required
def customer_give_payment(request, pk):
    """Record money the store pays back to the customer (refund / advance settlement)."""
    customer = get_object_or_404(Customer, pk=pk)
    if request.method == 'POST':
        form = CustomerPaymentForm(request.POST)
        if form.is_valid():
            amount = form.cleaned_data['amount']
            desc = form.cleaned_data['description'] or 'Payment given to customer'
            try:
                finance_services.record_payment(
                    Payment.Direction.OUT, amount, _cash_account(), timezone.localdate(),
                    customer=customer, note=desc, created_by=request.user, register=form.cleaned_data.get('register'),
                )
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, f'Payment of {amount} given to {customer.name}.')
        else:
            messages.error(request, 'Could not record payment — check the amount.')
    return redirect('customers:customer_detail', pk=pk)


@login_required
@require_POST
def customer_record_payment_api(request, pk):
    """AJAX endpoint used by the sale screen and customer list.
    direction='in' -> customer pays the store (reduces balance owed to store).
    direction='out' -> store pays the customer back (increases balance owed to store,
    i.e. clears what the store owes the customer)."""
    customer = get_object_or_404(Customer, pk=pk)
    try:
        amount = Decimal(request.POST.get('amount', '0'))
    except InvalidOperation:
        amount = Decimal('0')
    if amount <= 0:
        return JsonResponse({'error': 'Valid amount is required.'}, status=400)
    direction = request.POST.get('direction', 'in')
    if direction == 'out' and not request.user.is_manager():
        # Receiving money from a customer is a normal cashier task; paying
        # money back out is not — same policy as customers.customer_give_payment.
        return JsonResponse({'error': 'Only a manager can record money paid back to a customer.'}, status=403)
    note = 'Payment given to customer' if direction == 'out' else 'Old due payment received'
    register_id = request.POST.get('register')
    register = CashRegister.objects.filter(pk=register_id).first() if register_id else None
    account = finance_services.get_or_create_register_account(register) if register else _cash_account()
    try:
        if direction == 'out':
            finance_services.record_payment(
                Payment.Direction.OUT, amount, account, timezone.localdate(),
                customer=customer, note=note, created_by=request.user,
            )
        else:
            # Pays off the customer's oldest outstanding sale(s) first (FIFO) so
            # this actually shows up on the bill(s) it settled — see _collect_due.
            _collect_due(customer, amount, account, timezone.localdate(), note, request.user)
    except ValueError as exc:
        # Covers a concurrent double-submit racing past the amount<=0 check
        # above or against a since-changed invoice remaining balance — the
        # underlying select_for_update in record_payment/allocate_payment is
        # what actually prevents the duplicate; this just reports it cleanly
        # instead of a 500.
        return JsonResponse({'error': str(exc)}, status=400)
    return JsonResponse({'balance': str(customer.current_balance)})
