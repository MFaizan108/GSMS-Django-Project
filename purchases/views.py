from decimal import Decimal

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from accounts.decorators import manager_required
from finance import services as finance_services
from finance.forms import PaymentEntryForm
from finance.models import Payment
from products.models import Product
from inventory.models import WarehouseStock
from .models import Purchase, PurchaseReturn, PurchaseOrder, PurchaseOrderItem
from .forms import (
    PurchaseForm, PurchaseItemFormSet, PurchaseReturnForm, PurchaseReturnItemFormSet,
    PurchaseOrderForm, PurchaseOrderItemFormSet,
)
from . import services
from core.pdf import render_to_pdf
from settings_app.models import StoreSettings


@login_required
def purchase_list(request):
    purchases = Purchase.objects.select_related('supplier', 'warehouse').all()
    if request.user.branch_id:
        purchases = purchases.filter(warehouse_id=request.user.branch_id)
    return render(request, 'purchases/purchase_list.html', {'purchases': purchases})


@login_required
def purchase_detail(request, pk):
    purchase = get_object_or_404(Purchase, pk=pk)
    payment_form = PaymentEntryForm()
    can_return = any(item.returnable_quantity > 0 for item in purchase.items.all())
    can_cancel = (
        purchase.status != Purchase.Status.CANCELLED
        and not purchase.payments.exists() and not purchase.payment_allocations.exists() and not purchase.returns.exists()
    )
    return render(request, 'purchases/purchase_detail.html', {
        'purchase': purchase, 'payment_form': payment_form, 'can_return': can_return, 'can_cancel': can_cancel,
    })


@manager_required
@require_POST
def purchase_cancel(request, pk):
    purchase = get_object_or_404(Purchase, pk=pk)
    try:
        services.cancel_purchase(purchase, request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f'Purchase #{purchase.invoice_no} cancelled — stock and ledger reversed.')
    return redirect('purchases:purchase_detail', pk=pk)


@login_required
def purchase_invoice_pdf(request, pk):
    purchase = get_object_or_404(Purchase, pk=pk)
    pdf_bytes = render_to_pdf('purchases/purchase_invoice_pdf.html', {'purchase': purchase, 'store_settings': StoreSettings.get_solo()})
    if pdf_bytes is None:
        messages.error(request, 'Could not generate the PDF invoice.')
        return redirect('purchases:purchase_detail', pk=pk)
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="purchase-{purchase.invoice_no}.pdf"'
    return response


@login_required
@require_GET
def purchase_product_search_api(request):
    q = request.GET.get('q', '').strip()
    warehouse_id = request.GET.get('warehouse_id')
    products = Product.objects.filter(status=Product.Status.ACTIVE).select_related('unit')
    if q:
        products = products.filter(
            Q(name__icontains=q) | Q(barcode__icontains=q) | Q(sku__icontains=q) | Q(barcodes__barcode__icontains=q)
        ).distinct()
    products = products.order_by('name')[:15]

    stock_by_product = None
    if warehouse_id and warehouse_id.isdigit():
        stock_by_product = {
            row['product_id']: row['quantity']
            for row in WarehouseStock.objects.filter(warehouse_id=warehouse_id, product__in=products).values('product_id', 'quantity')
        }

    results = [{
        'id': p.id,
        'name': p.name,
        'barcode': p.barcode or '',
        'price': str(p.purchase_price),
        'stock': str(stock_by_product.get(p.id, Decimal('0'))) if stock_by_product is not None else str(p.stock),
        'unit': (p.unit.short_name or p.unit.name) if p.unit else '',
    } for p in products]
    return JsonResponse({'results': results})


@manager_required
def purchase_create(request):
    from_po = None
    from_po_id = request.GET.get('from_po') or request.POST.get('from_po')
    if from_po_id:
        from_po = get_object_or_404(PurchaseOrder, pk=from_po_id)

    if request.method == 'POST':
        form = PurchaseForm(request.POST, user=request.user)
        formset = PurchaseItemFormSet(request.POST, instance=Purchase())
        if form.is_valid() and formset.is_valid():
            items_data = []
            for f in formset:
                if f.cleaned_data and not f.cleaned_data.get('DELETE') and f.cleaned_data.get('product'):
                    po_item_id = f.cleaned_data.get('purchase_order_item_id')
                    items_data.append({
                        'product': f.cleaned_data['product'],
                        'quantity': f.cleaned_data['quantity'],
                        'purchase_price': f.cleaned_data['purchase_price'],
                        'expiry_date': f.cleaned_data.get('expiry_date'),
                        'batch_number': f.cleaned_data.get('batch_number', ''),
                        'purchase_order_item': PurchaseOrderItem.objects.filter(pk=po_item_id).first() if po_item_id else None,
                    })

            if not items_data:
                messages.error(request, 'Add at least one item to the purchase.')
            else:
                purchase = form.save(commit=False)
                amount_paid_now = form.cleaned_data.get('amount_paid_now') or Decimal('0')
                register = form.cleaned_data.get('register')
                purchase = services.create_purchase(purchase, items_data, amount_paid_now, request.user, register=register)
                messages.success(request, 'Purchase recorded, stock updated, supplier ledger updated.')
                return redirect('purchases:purchase_detail', pk=purchase.pk)
    elif from_po:
        next_invoice = f"INV-{Purchase.objects.count() + 1:05d}"
        form = PurchaseForm(initial={
            'supplier': from_po.supplier_id, 'warehouse': from_po.warehouse_id,
            'invoice_no': next_invoice, 'date': timezone.localdate(),
        }, user=request.user)
        formset = PurchaseItemFormSet(instance=Purchase())
    else:
        form = PurchaseForm(user=request.user)
        formset = PurchaseItemFormSet(instance=Purchase())

    # Rebuild the bill-builder's cart from bound/from-PO data so a validation
    # error (or the from_po prefill) survives the redisplay — same pattern as
    # sales.views.sale_create's prefill_items.
    warehouse_id = form['warehouse'].value()
    stock_by_product = {}
    if warehouse_id:
        stock_by_product = {
            row['product_id']: row['quantity']
            for row in WarehouseStock.objects.filter(warehouse_id=warehouse_id).values('product_id', 'quantity')
        }

    prefill_items = []
    if request.method == 'POST':
        for f in formset.forms:
            product_id = f['product'].value()
            if not product_id or f['DELETE'].value():
                continue
            try:
                product = Product.objects.select_related('unit').get(pk=product_id)
            except (Product.DoesNotExist, ValueError, TypeError):
                continue
            prefill_items.append({
                'product_id': product.id,
                'name': product.name,
                'unit': (product.unit.short_name or product.unit.name) if product.unit else '',
                'price': str(f['purchase_price'].value() or product.purchase_price),
                'qty': str(f['quantity'].value() or '1'),
                'stock': str(stock_by_product.get(product.id, Decimal('0'))),
                'expiry_date': f['expiry_date'].value() or '',
                'batch_number': f['batch_number'].value() or '',
                'purchase_order_item_id': f['purchase_order_item_id'].value() or '',
            })
    elif from_po:
        for i in from_po.items.all():
            if i.pending_quantity <= 0:
                continue
            prefill_items.append({
                'product_id': i.product_id,
                'name': str(i.product),
                'unit': (i.product.unit.short_name or i.product.unit.name) if i.product.unit else '',
                'price': str(i.expected_price),
                'qty': str(i.pending_quantity),
                'stock': str(stock_by_product.get(i.product_id, Decimal('0'))),
                'expiry_date': '',
                'batch_number': '',
                'purchase_order_item_id': i.pk,
            })

    context = {'form': form, 'formset': formset, 'from_po': from_po, 'prefill_items': prefill_items}
    return render(request, 'purchases/purchase_form.html', context)


@manager_required
@require_POST
def purchase_add_payment(request, pk):
    purchase = get_object_or_404(Purchase, pk=pk)
    form = PaymentEntryForm(request.POST)
    if form.is_valid():
        try:
            finance_services.record_payment(
                Payment.Direction.OUT, form.cleaned_data['amount'], form.cleaned_data['account'],
                form.cleaned_data['date'], purchase=purchase, supplier=purchase.supplier,
                note=form.cleaned_data.get('note', ''), created_by=request.user,
            )
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            purchase.recalculate()
            messages.success(request, 'Payment recorded.')
    else:
        messages.error(request, 'Could not record payment — check the amount and account.')
    return redirect('purchases:purchase_detail', pk=pk)


@login_required
def purchase_return_list(request):
    returns = PurchaseReturn.objects.select_related('purchase', 'purchase__supplier').all()
    return render(request, 'purchases/purchase_return_list.html', {'returns': returns})


@login_required
def purchase_return_detail(request, pk):
    purchase_return = get_object_or_404(PurchaseReturn, pk=pk)
    return render(request, 'purchases/purchase_return_detail.html', {'purchase_return': purchase_return})


@login_required
def purchase_order_list(request):
    orders = PurchaseOrder.objects.select_related('supplier', 'warehouse').all()
    if request.user.branch_id:
        orders = orders.filter(warehouse_id=request.user.branch_id)
    return render(request, 'purchases/purchase_order_list.html', {'orders': orders})


@login_required
def purchase_order_detail(request, pk):
    order = get_object_or_404(PurchaseOrder, pk=pk)
    return render(request, 'purchases/purchase_order_detail.html', {'order': order})


@manager_required
def purchase_order_create(request):
    if request.method == 'POST':
        form = PurchaseOrderForm(request.POST, user=request.user)
        formset = PurchaseOrderItemFormSet(request.POST, instance=PurchaseOrder())
        if form.is_valid() and formset.is_valid():
            items_data = []
            for f in formset:
                if f.cleaned_data and not f.cleaned_data.get('DELETE') and f.cleaned_data.get('product'):
                    items_data.append({
                        'product': f.cleaned_data['product'],
                        'quantity': f.cleaned_data['quantity'],
                        'expected_price': f.cleaned_data['expected_price'],
                    })
            if not items_data:
                messages.error(request, 'Add at least one item to the order.')
            else:
                order = form.save(commit=False)
                order = services.create_purchase_order(order, items_data, request.user)
                messages.success(request, 'Purchase order created.')
                return redirect('purchases:purchase_order_detail', pk=order.pk)
    else:
        next_order_no = f"PO-{PurchaseOrder.objects.count() + 1:05d}"
        form = PurchaseOrderForm(initial={'date': timezone.localdate(), 'order_no': next_order_no}, user=request.user)
        formset = PurchaseOrderItemFormSet(instance=PurchaseOrder())

    prefill_items = []
    if request.method == 'POST':
        for f in formset.forms:
            product_id = f['product'].value()
            if not product_id or f['DELETE'].value():
                continue
            try:
                product = Product.objects.select_related('unit').get(pk=product_id)
            except (Product.DoesNotExist, ValueError, TypeError):
                continue
            prefill_items.append({
                'product_id': product.id,
                'name': product.name,
                'unit': (product.unit.short_name or product.unit.name) if product.unit else '',
                'price': str(f['expected_price'].value() or product.purchase_price),
                'qty': str(f['quantity'].value() or '1'),
            })

    context = {'form': form, 'formset': formset, 'prefill_items': prefill_items}
    return render(request, 'purchases/purchase_order_form.html', context)


@manager_required
def purchase_return_create(request, purchase_pk):
    purchase = get_object_or_404(Purchase, pk=purchase_pk)
    if request.method == 'POST':
        form = PurchaseReturnForm(request.POST)
        formset = PurchaseReturnItemFormSet(request.POST, instance=PurchaseReturn(), form_kwargs={'purchase': purchase})
        if form.is_valid() and formset.is_valid():
            items_data = []
            for f in formset:
                if f.cleaned_data and not f.cleaned_data.get('DELETE') and f.cleaned_data.get('purchase_item'):
                    items_data.append({
                        'purchase_item': f.cleaned_data['purchase_item'],
                        'quantity': f.cleaned_data['quantity'],
                    })
            if not items_data:
                messages.error(request, 'Add at least one item to return.')
            else:
                purchase_return = form.save(commit=False)
                purchase_return.purchase = purchase
                try:
                    purchase_return = services.create_purchase_return(purchase_return, items_data, request.user)
                except ValueError as exc:
                    messages.error(request, str(exc))
                else:
                    messages.success(request, 'Purchase return recorded.')
                    return redirect('purchases:purchase_detail', pk=purchase.pk)
    else:
        next_return_no = f"PR-{PurchaseReturn.objects.count() + 1:05d}"
        form = PurchaseReturnForm(initial={'date': timezone.localdate(), 'return_no': next_return_no})
        formset = PurchaseReturnItemFormSet(instance=PurchaseReturn(), form_kwargs={'purchase': purchase})
    return render(request, 'purchases/purchase_return_form.html', {'form': form, 'formset': formset, 'purchase': purchase})
