from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required

from accounts.decorators import manager_required
from customers.models import Customer
from suppliers.models import Supplier
from sales.models import Sale
from purchases.models import Purchase
from finance.models import Payment
from . import services
from .forms import AllocationHeaderForm, InvoiceAllocationFormSet


@login_required
def customer_payment_allocate(request, customer_id):
    customer = get_object_or_404(Customer, pk=customer_id)
    outstanding = list(Sale.objects.filter(customer=customer, remaining__gt=0).order_by('date'))

    if request.method == 'POST':
        header_form = AllocationHeaderForm(request.POST)
        formset = InvoiceAllocationFormSet(request.POST, initial=[{'invoice_id': s.pk} for s in outstanding])
        if header_form.is_valid() and formset.is_valid():
            invoice_by_id = {s.pk: s for s in outstanding}
            allocations = [
                (invoice_by_id[f.cleaned_data['invoice_id']], f.cleaned_data.get('amount'))
                for f in formset if f.cleaned_data.get('invoice_id') in invoice_by_id
            ]
            try:
                services.allocate_payment(
                    Payment.Direction.IN, header_form.cleaned_data['account'], header_form.cleaned_data['date'],
                    allocations, customer=customer, note=header_form.cleaned_data.get('note', ''),
                    created_by=request.user,
                )
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, 'Payment allocated across invoices.')
                return redirect('customers:customer_detail', pk=customer.pk)
    else:
        header_form = AllocationHeaderForm()
        formset = InvoiceAllocationFormSet(initial=[{'invoice_id': s.pk} for s in outstanding])

    rows = list(zip(outstanding, formset.forms))
    return render(request, 'payments/customer_payment_allocate.html', {
        'customer': customer, 'header_form': header_form, 'formset': formset, 'rows': rows,
    })


@manager_required
def supplier_payment_allocate(request, supplier_id):
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    outstanding = list(Purchase.objects.filter(supplier=supplier, remaining__gt=0).order_by('date'))

    if request.method == 'POST':
        header_form = AllocationHeaderForm(request.POST)
        formset = InvoiceAllocationFormSet(request.POST, initial=[{'invoice_id': p.pk} for p in outstanding])
        if header_form.is_valid() and formset.is_valid():
            invoice_by_id = {p.pk: p for p in outstanding}
            allocations = [
                (invoice_by_id[f.cleaned_data['invoice_id']], f.cleaned_data.get('amount'))
                for f in formset if f.cleaned_data.get('invoice_id') in invoice_by_id
            ]
            try:
                services.allocate_payment(
                    Payment.Direction.OUT, header_form.cleaned_data['account'], header_form.cleaned_data['date'],
                    allocations, supplier=supplier, note=header_form.cleaned_data.get('note', ''),
                    created_by=request.user,
                )
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, 'Payment allocated across invoices.')
                return redirect('suppliers:supplier_detail', pk=supplier.pk)
    else:
        header_form = AllocationHeaderForm()
        formset = InvoiceAllocationFormSet(initial=[{'invoice_id': p.pk} for p in outstanding])

    rows = list(zip(outstanding, formset.forms))
    return render(request, 'payments/supplier_payment_allocate.html', {
        'supplier': supplier, 'header_form': header_form, 'formset': formset, 'rows': rows,
    })
