from decimal import Decimal
from urllib.parse import quote

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse, HttpResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from finance import services as finance_services
from finance.forms import PaymentEntryForm
from finance.models import Payment
from .models import Sale, SalesReturn
from .forms import SaleForm, SaleItemFormSet, SalesReturnForm, SalesReturnItemFormSet
from . import services as sales_services
from customers.models import Customer
from products.models import Product
from inventory.models import WarehouseStock
from inventory.services import InsufficientStockError
from core.pdf import render_to_pdf
from core.mail import send_store_email, EmailNotConfigured
from settings_app.models import StoreSettings


def _whatsapp_number(phone):
    """Convert a locally-stored Pakistani number (e.g. '0333-7654321') into
    the full international digits wa.me needs (e.g. '923337654321') — wa.me
    silently fails (blank/black chat window) on a local-format number with
    its leading 0 still attached. Returns '' if the number looks too short
    to be real."""
    digits = ''.join(ch for ch in (phone or '') if ch.isdigit())
    if digits.startswith('0') and len(digits) == 11:
        digits = '92' + digits[1:]
    if len(digits) < 10:
        return ''
    return digits


@login_required
def sale_list(request):
    sales = Sale.objects.select_related('customer').all()
    if request.user.branch_id:
        sales = sales.filter(warehouse_id=request.user.branch_id)

    q = request.GET.get('q', '').strip()
    if q:
        sales = sales.filter(Q(invoice_no__icontains=q) | Q(customer__name__icontains=q))
    date = request.GET.get('date', '').strip()
    if date:
        sales = sales.filter(date=date)

    return render(request, 'sales/sale_list.html', {'sales': sales, 'q': q, 'date': date})


@login_required
def sale_detail(request, pk):
    sale = get_object_or_404(Sale, pk=pk)
    payment_form = PaymentEntryForm() if sale.customer else None
    can_return = any(item.returnable_quantity > 0 for item in sale.items.all())
    can_cancel = (
        sale.status != Sale.Status.CANCELLED
        and not sale.payments.exists() and not sale.payment_allocations.exists() and not sale.returns.exists()
    )

    whatsapp_link = None
    if sale.customer and sale.customer.phone:
        digits = _whatsapp_number(sale.customer.phone)
        if digits:
            bill_url = request.build_absolute_uri(reverse('sales:sale_invoice_public', args=[sale.public_token]))
            text = quote(
                f"Invoice #{sale.invoice_no} — Total: {sale.total} — Thank you for shopping with us!\n"
                f"View/download your bill: {bill_url}"
            )
            whatsapp_link = f"https://wa.me/{digits}?text={text}"

    return render(request, 'sales/sale_detail.html', {
        'sale': sale, 'payment_form': payment_form, 'can_return': can_return, 'can_cancel': can_cancel,
        'whatsapp_link': whatsapp_link,
    })


@login_required
@require_POST
def sale_cancel(request, pk):
    sale = get_object_or_404(Sale, pk=pk)
    try:
        sales_services.cancel_sale(sale, request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f'Sale #{sale.invoice_no} cancelled — stock and ledger reversed.')
    return redirect('sales:sale_detail', pk=pk)


@login_required
def sale_invoice_pdf(request, pk):
    sale = get_object_or_404(Sale, pk=pk)
    pdf_bytes = render_to_pdf('sales/sale_invoice_pdf.html', {'sale': sale, 'store_settings': StoreSettings.get_solo()})
    if pdf_bytes is None:
        messages.error(request, 'Could not generate the PDF invoice.')
        return redirect('sales:sale_detail', pk=pk)
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="invoice-{sale.invoice_no}.pdf"'
    return response


def sale_invoice_public_pdf(request, token):
    """No @login_required — this is the link shared via WhatsApp/SMS so a
    customer can view their own bill without an account. Reachable only
    with the sale's own unguessable public_token, never by pk."""
    sale = get_object_or_404(Sale, public_token=token)
    pdf_bytes = render_to_pdf('sales/sale_invoice_pdf.html', {'sale': sale, 'store_settings': StoreSettings.get_solo()})
    if pdf_bytes is None:
        return HttpResponse('Could not generate the PDF invoice.', status=500)
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="invoice-{sale.invoice_no}.pdf"'
    return response


@login_required
@require_POST
def sale_email_invoice(request, pk):
    sale = get_object_or_404(Sale, pk=pk)
    if not sale.customer or not sale.customer.email:
        messages.error(request, 'This sale has no customer email on file.')
        return redirect('sales:sale_detail', pk=pk)

    store = StoreSettings.get_solo()
    pdf_bytes = render_to_pdf('sales/sale_invoice_pdf.html', {'sale': sale, 'store_settings': store})
    if pdf_bytes is None:
        messages.error(request, 'Could not generate the PDF invoice.')
        return redirect('sales:sale_detail', pk=pk)

    try:
        send_store_email(
            subject=f"Invoice #{sale.invoice_no} — {store.store_name}",
            body=f"Dear {sale.customer.name},\n\nPlease find attached your invoice #{sale.invoice_no} for {sale.total}.\n\n{store.invoice_footer}",
            to=sale.customer.email,
            attachments=[(f"invoice-{sale.invoice_no}.pdf", pdf_bytes, 'application/pdf')],
        )
    except EmailNotConfigured as exc:
        messages.error(request, str(exc))
    except Exception:
        messages.error(request, 'Could not send the email — check the SMTP settings and try again.')
    else:
        messages.success(request, f'Invoice emailed to {sale.customer.email}.')
    return redirect('sales:sale_detail', pk=pk)


@login_required
@require_GET
def product_search_api(request):
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
        'price': str(p.retail_price),
        'stock': str(stock_by_product.get(p.id, Decimal('0'))) if stock_by_product is not None else str(p.stock),
        'unit': (p.unit.short_name or p.unit.name) if p.unit else '',
    } for p in products]
    return JsonResponse({'results': results})


@login_required
@require_GET
def customer_search_api(request):
    q = request.GET.get('q', '').strip()
    customers = Customer.objects.all()
    if q:
        customers = customers.filter(Q(name__icontains=q) | Q(phone__icontains=q))
    customers = customers.order_by('name')[:15]
    results = [{
        'id': c.id,
        'name': c.name,
        'phone': c.phone,
        'balance': str(c.current_balance),
    } for c in customers]
    return JsonResponse({'results': results})


@login_required
@require_POST
def customer_quick_create_api(request):
    name = request.POST.get('name', '').strip()
    phone = request.POST.get('phone', '').strip()
    if not name:
        return JsonResponse({'error': 'Customer name is required.'}, status=400)
    customer = Customer.objects.create(name=name, phone=phone)
    return JsonResponse({'id': customer.id, 'name': customer.name, 'phone': customer.phone, 'balance': str(customer.current_balance)})


@login_required
def sale_create(request):
    if request.method == 'POST':
        form = SaleForm(request.POST, user=request.user)
        formset = SaleItemFormSet(request.POST, instance=Sale())
        if form.is_valid() and formset.is_valid():
            items_data = []
            for f in formset:
                if f.cleaned_data and not f.cleaned_data.get('DELETE') and f.cleaned_data.get('product'):
                    items_data.append({
                        'product': f.cleaned_data['product'],
                        'quantity': f.cleaned_data['quantity'],
                        'selling_price': f.cleaned_data['selling_price'],
                    })

            if not items_data:
                messages.error(request, 'Add at least one item to the sale.')
            else:
                sale = form.save(commit=False)
                amount_paid_now = form.cleaned_data.get('amount_paid_now') or Decimal('0')
                register = form.cleaned_data.get('register')
                try:
                    sale = sales_services.create_sale(sale, items_data, amount_paid_now, request.user, register=register)
                except InsufficientStockError as exc:
                    messages.error(request, str(exc))
                else:
                    change_given = amount_paid_now - sale.total
                    if sale.customer and change_given > 0:
                        messages.success(request, f'Sale recorded, stock updated, profit calculated. Change given: {change_given}.')
                    else:
                        messages.success(request, 'Sale recorded, stock updated, profit calculated.')
                    return redirect('sales:sale_detail', pk=sale.pk)
    else:
        next_invoice = f"INV-{Sale.objects.count() + 1:05d}"
        form = SaleForm(initial={'date': timezone.localdate(), 'invoice_no': next_invoice}, user=request.user)
        formset = SaleItemFormSet(instance=Sale())

    # Rebuild the bill-builder's cart/customer from bound data so a validation
    # error (e.g. insufficient stock) doesn't wipe what the cashier entered.
    warehouse_id = form['warehouse'].value()
    stock_by_product = {}
    if warehouse_id:
        stock_by_product = {
            row['product_id']: row['quantity']
            for row in WarehouseStock.objects.filter(warehouse_id=warehouse_id).values('product_id', 'quantity')
        }

    prefill_items = []
    for f in formset.forms:
        product_id = f['product'].value()
        if not product_id or f['DELETE'].value():
            continue
        try:
            product = Product.objects.select_related('unit').get(pk=product_id)
        except (Product.DoesNotExist, ValueError, TypeError):
            continue
        qty = f['quantity'].value() or '1'
        price = f['selling_price'].value() or product.retail_price
        prefill_items.append({
            'product_id': product.id,
            'name': product.name,
            'unit': (product.unit.short_name or product.unit.name) if product.unit else '',
            'price': str(price),
            'qty': str(qty),
            'stock': str(stock_by_product.get(product.id, product.stock)),
        })

    prefill_customer = None
    customer_id = form['customer'].value()
    if customer_id:
        try:
            c = Customer.objects.get(pk=customer_id)
            prefill_customer = {'id': c.id, 'name': c.name, 'phone': c.phone, 'balance': str(c.current_balance)}
        except (Customer.DoesNotExist, ValueError, TypeError):
            pass

    context = {
        'form': form,
        'formset': formset,
        'prefill_items': prefill_items,
        'prefill_customer': prefill_customer,
    }
    return render(request, 'sales/sale_form.html', context)


@login_required
@require_POST
def sale_add_payment(request, pk):
    sale = get_object_or_404(Sale, pk=pk)
    if not sale.customer:
        messages.error(request, 'This sale has no customer to record a payment against.')
        return redirect('sales:sale_detail', pk=pk)
    form = PaymentEntryForm(request.POST)
    if form.is_valid():
        try:
            finance_services.record_payment(
                Payment.Direction.IN, form.cleaned_data['amount'], form.cleaned_data['account'],
                form.cleaned_data['date'], sale=sale, customer=sale.customer,
                note=form.cleaned_data.get('note', ''), created_by=request.user,
            )
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            sale.recalculate()
            messages.success(request, 'Payment recorded.')
    else:
        messages.error(request, 'Could not record payment — check the amount and account.')
    return redirect('sales:sale_detail', pk=pk)


@login_required
def sales_return_list(request):
    returns = SalesReturn.objects.select_related('sale', 'sale__customer').all()
    return render(request, 'sales/sales_return_list.html', {'returns': returns})


@login_required
def sales_return_detail(request, pk):
    sales_return = get_object_or_404(SalesReturn, pk=pk)
    return render(request, 'sales/sales_return_detail.html', {'sales_return': sales_return})


@login_required
def sales_return_create(request, sale_pk):
    sale = get_object_or_404(Sale, pk=sale_pk)
    if request.method == 'POST':
        form = SalesReturnForm(request.POST)
        formset = SalesReturnItemFormSet(request.POST, instance=SalesReturn(), form_kwargs={'sale': sale})
        if form.is_valid() and formset.is_valid():
            items_data = []
            for f in formset:
                if f.cleaned_data and not f.cleaned_data.get('DELETE') and f.cleaned_data.get('sale_item'):
                    items_data.append({
                        'sale_item': f.cleaned_data['sale_item'],
                        'quantity': f.cleaned_data['quantity'],
                        'condition': f.cleaned_data['condition'],
                    })
            if not items_data:
                messages.error(request, 'Add at least one item to return.')
            else:
                sales_return = form.save(commit=False)
                sales_return.sale = sale
                try:
                    sales_return = sales_services.create_sales_return(sales_return, items_data, request.user)
                except ValueError as exc:
                    messages.error(request, str(exc))
                else:
                    messages.success(request, 'Sales return recorded.')
                    return redirect('sales:sale_detail', pk=sale.pk)
    else:
        next_return_no = f"SR-{SalesReturn.objects.count() + 1:05d}"
        form = SalesReturnForm(initial={'date': timezone.localdate(), 'return_no': next_return_no})
        formset = SalesReturnItemFormSet(instance=SalesReturn(), form_kwargs={'sale': sale})
    return render(request, 'sales/sales_return_form.html', {'form': form, 'formset': formset, 'sale': sale})
