from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import ProtectedError
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.http import require_POST
from accounts.decorators import manager_required
from core.pdf import render_to_pdf
from finance import services as finance_services
from finance.models import Account, Payment
from settings_app.models import StoreSettings
from .models import Supplier
from .forms import SupplierForm, SupplierPaymentForm, BalanceAdjustmentForm


@login_required
def supplier_list(request):
    suppliers = Supplier.objects.all()
    return render(request, 'suppliers/supplier_list.html', {'suppliers': suppliers})


@login_required
def supplier_detail(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    start, end, kind = finance_services.parse_statement_filters(request.GET)
    ledger, stats = finance_services.get_party_statement(supplier, 'supplier', start=start, end=end, kind=kind)
    payment_form = SupplierPaymentForm(auto_id='id_pay_%s')
    refund_form = SupplierPaymentForm(auto_id='id_refund_%s')
    adjustment_form = BalanceAdjustmentForm()
    return render(request, 'suppliers/supplier_detail.html', {
        'supplier': supplier, 'ledger': ledger[:200], 'stats': stats,
        'payment_form': payment_form, 'refund_form': refund_form, 'adjustment_form': adjustment_form,
        'start': start or '', 'end': end or '', 'selected_kind': kind or '', 'kind_choices': finance_services.LEDGER_KINDS_SUPPLIER,
    })


@login_required
def supplier_statement_pdf(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    start, end, kind = finance_services.parse_statement_filters(request.GET)
    ledger, stats = finance_services.get_party_statement(supplier, 'supplier', start=start, end=end, kind=kind)
    pdf_bytes = render_to_pdf('suppliers/supplier_statement_pdf.html', {
        'supplier': supplier, 'ledger': ledger, 'stats': stats, 'start': start, 'end': end,
        'store_settings': StoreSettings.get_solo(),
    })
    if pdf_bytes is None:
        messages.error(request, 'Could not generate the statement PDF.')
        return redirect('suppliers:supplier_detail', pk=pk)
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="statement-{supplier.name}.pdf"'
    return response


@manager_required
def supplier_balance_adjustment(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    if request.method == 'POST':
        form = BalanceAdjustmentForm(request.POST)
        if form.is_valid():
            try:
                finance_services.post_balance_adjustment(
                    supplier, form.cleaned_data['amount'], timezone.localdate(),
                    form.cleaned_data['note'], created_by=request.user,
                )
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, 'Balance adjustment recorded.')
        else:
            messages.error(request, 'Could not record adjustment — check the amount and note.')
    return redirect('suppliers:supplier_detail', pk=pk)


@manager_required
def supplier_create(request):
    if request.method == 'POST':
        form = SupplierForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                supplier = form.save()
                finance_services.get_or_create_party_account(supplier, Account.Type.LIABILITY, Account.Subtype.AP)
                finance_services.post_opening_balance(
                    supplier.linked_account, supplier.opening_balance, timezone.localdate(), created_by=request.user,
                )
            messages.success(request, 'Supplier added.')
            return redirect('suppliers:supplier_list')
    else:
        form = SupplierForm()
    return render(request, 'suppliers/supplier_form.html', {'form': form, 'title': 'Add Supplier'})


@manager_required
def supplier_edit(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    if request.method == 'POST':
        form = SupplierForm(request.POST, instance=supplier)
        if form.is_valid():
            form.save()
            messages.success(request, 'Supplier updated.')
            return redirect('suppliers:supplier_list')
    else:
        form = SupplierForm(instance=supplier)
    return render(request, 'suppliers/supplier_form.html', {'form': form, 'title': 'Edit Supplier'})


@manager_required
@require_POST
def supplier_delete(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    try:
        supplier.delete()
        messages.success(request, 'Supplier deleted.')
    except ProtectedError:
        messages.error(request, f'Cannot delete {supplier.name} — this supplier has existing purchase records.')
    return redirect('suppliers:supplier_list')


@manager_required
def supplier_payment(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    if request.method == 'POST':
        form = SupplierPaymentForm(request.POST)
        if form.is_valid():
            amount = form.cleaned_data['amount']
            desc = form.cleaned_data['description'] or 'Payment to supplier'
            try:
                finance_services.record_payment(
                    Payment.Direction.OUT, amount, finance_services.get_account('1000'), timezone.localdate(),
                    supplier=supplier, note=desc, created_by=request.user, register=form.cleaned_data.get('register'),
                )
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, f'Payment of {amount} recorded.')
        else:
            messages.error(request, 'Could not record payment — check the amount.')
    return redirect('suppliers:supplier_detail', pk=pk)


@manager_required
def supplier_receive_refund(request, pk):
    """Record cash the supplier sends back to the store — e.g. a purchase
    return refund, once the supplier's balance shows they owe us money."""
    supplier = get_object_or_404(Supplier, pk=pk)
    if request.method == 'POST':
        form = SupplierPaymentForm(request.POST)
        if form.is_valid():
            amount = form.cleaned_data['amount']
            desc = form.cleaned_data['description'] or 'Refund received from supplier'
            try:
                finance_services.record_payment(
                    Payment.Direction.IN, amount, finance_services.get_account('1000'), timezone.localdate(),
                    supplier=supplier, note=desc, created_by=request.user, register=form.cleaned_data.get('register'),
                )
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, f'Refund of {amount} received from {supplier.name}.')
        else:
            messages.error(request, 'Could not record payment — check the amount.')
    return redirect('suppliers:supplier_detail', pk=pk)
