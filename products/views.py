from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import ProtectedError, Q
from django.http import HttpResponse
from django.views.decorators.http import require_POST
from accounts.decorators import manager_required
from .models import Category, Brand, Unit, Product
from .forms import CategoryForm, BrandForm, UnitForm, ProductForm
from .barcodes import generate_barcode_data_uri
from .excel import export_products_workbook, import_products_from_workbook
from openpyxl import load_workbook


# ---------- Category ----------
@login_required
def category_list(request):
    categories = Category.objects.all()
    return render(request, 'products/category_list.html', {'categories': categories})


@manager_required
def category_create(request):
    if request.method == 'POST':
        form = CategoryForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Category added.')
            return redirect('products:category_list')
    else:
        form = CategoryForm()
    return render(request, 'products/simple_form.html', {'form': form, 'title': 'Add Category'})


@manager_required
def category_edit(request, pk):
    category = get_object_or_404(Category, pk=pk)
    if request.method == 'POST':
        form = CategoryForm(request.POST, instance=category)
        if form.is_valid():
            form.save()
            messages.success(request, 'Category updated.')
            return redirect('products:category_list')
    else:
        form = CategoryForm(instance=category)
    return render(request, 'products/simple_form.html', {'form': form, 'title': 'Edit Category'})


@manager_required
@require_POST
def category_delete(request, pk):
    category = get_object_or_404(Category, pk=pk)
    category.delete()
    messages.success(request, 'Category deleted.')
    return redirect('products:category_list')


# ---------- Brand ----------
@login_required
def brand_list(request):
    brands = Brand.objects.all()
    return render(request, 'products/brand_list.html', {'brands': brands})


@manager_required
def brand_create(request):
    if request.method == 'POST':
        form = BrandForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Brand added.')
            return redirect('products:brand_list')
    else:
        form = BrandForm()
    return render(request, 'products/simple_form.html', {'form': form, 'title': 'Add Brand'})


@manager_required
@require_POST
def brand_delete(request, pk):
    get_object_or_404(Brand, pk=pk).delete()
    messages.success(request, 'Brand deleted.')
    return redirect('products:brand_list')


# ---------- Unit ----------
@login_required
def unit_list(request):
    units = Unit.objects.all()
    return render(request, 'products/unit_list.html', {'units': units})


@manager_required
def unit_create(request):
    if request.method == 'POST':
        form = UnitForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Unit added.')
            return redirect('products:unit_list')
    else:
        form = UnitForm()
    return render(request, 'products/simple_form.html', {'form': form, 'title': 'Add Unit'})


@manager_required
@require_POST
def unit_delete(request, pk):
    get_object_or_404(Unit, pk=pk).delete()
    messages.success(request, 'Unit deleted.')
    return redirect('products:unit_list')


# ---------- Product ----------
@login_required
def product_list(request):
    products = Product.objects.select_related('category', 'brand', 'unit').all()
    q = request.GET.get('q', '').strip()
    if q:
        products = products.filter(
            Q(name__icontains=q) | Q(barcode__icontains=q) | Q(sku__icontains=q)
        )
    category_id = request.GET.get('category', '').strip()
    category = None
    if category_id:
        products = products.filter(category_id=category_id)
        category = get_object_or_404(Category, pk=category_id)
    return render(request, 'products/product_list.html', {'products': products, 'q': q, 'category': category})


@login_required
def product_detail(request, pk):
    product = get_object_or_404(Product, pk=pk)
    return render(request, 'products/product_detail.html', {'product': product})


@manager_required
def product_create(request):
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Product added.')
            return redirect('products:product_list')
    else:
        initial = {}
        category_id = request.GET.get('category', '').strip()
        if category_id:
            initial['category'] = category_id
        form = ProductForm(initial=initial, user=request.user)
    return render(request, 'products/product_form.html', {'form': form, 'title': 'Add Product'})


@manager_required
def product_edit(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES, instance=product, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Product updated.')
            return redirect('products:product_list')
    else:
        form = ProductForm(instance=product, user=request.user)
    return render(request, 'products/product_form.html', {'form': form, 'title': 'Edit Product'})


@manager_required
@require_POST
def product_delete(request, pk):
    product = get_object_or_404(Product, pk=pk)
    try:
        product.delete()
        messages.success(request, 'Product deleted.')
    except ProtectedError:
        messages.error(request, f'Cannot delete {product.name} — this product has existing sale or purchase records.')
    return redirect('products:product_list')


@login_required
def product_barcode_label(request, pk):
    """Printable sheet of barcode labels for one product. If the product has
    no barcode yet, assigns a deterministic internal one (PRD########) and
    saves it — a printed label is useless unless it matches a real, scannable
    code the product search API can actually look up."""
    product = get_object_or_404(Product, pk=pk)
    if not product.barcode:
        product.barcode = f"PRD{product.pk:08d}"
        product.save(update_fields=['barcode'])

    try:
        qty = max(1, min(int(request.GET.get('qty', 1)), 100))
    except ValueError:
        qty = 1

    return render(request, 'products/barcode_label.html', {
        'product': product,
        'barcode_image': generate_barcode_data_uri(product.barcode),
        'copies': range(qty),
    })


@login_required
def product_export_excel(request):
    products = Product.objects.select_related('category', 'brand', 'unit', 'tax').all()
    wb = export_products_workbook(products)
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename="products.xlsx"'
    wb.save(response)
    return response


@manager_required
def product_import_excel(request):
    if request.method == 'POST':
        upload = request.FILES.get('file')
        if not upload:
            messages.error(request, 'Please choose an .xlsx file to import.')
        else:
            try:
                wb = load_workbook(filename=upload, data_only=True)
            except Exception:
                messages.error(request, 'Could not read that file — please upload a valid .xlsx exported from this system (or matching its column headers).')
            else:
                created, updated, errors = import_products_from_workbook(wb)
                if created or updated:
                    messages.success(request, f'Import complete: {created} product(s) created, {updated} updated.')
                if errors:
                    preview = '; '.join(f"row {n}: {msg}" for n, msg in errors[:10])
                    messages.warning(request, f'{len(errors)} row(s) had issues — {preview}')
                if not created and not updated and not errors:
                    messages.warning(request, 'No rows found to import.')
                return redirect('products:product_list')
    return render(request, 'products/import_excel.html', {})
