from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from accounts.decorators import manager_required
from .models import StockAdjustment, WarehouseStock
from .forms import StockAdjustmentForm
from . import services


@login_required
def adjustment_list(request):
    adjustments = StockAdjustment.objects.select_related('product', 'warehouse').all()
    if request.user.branch_id:
        adjustments = adjustments.filter(warehouse_id=request.user.branch_id)
    return render(request, 'inventory/adjustment_list.html', {'adjustments': adjustments})


@manager_required
def adjustment_create(request):
    if request.method == 'POST':
        form = StockAdjustmentForm(request.POST, user=request.user)
        if form.is_valid():
            adjustment = form.save(commit=False)

            if adjustment.adjust_type == StockAdjustment.AdjustType.DECREASE:
                ws = WarehouseStock.objects.filter(product=adjustment.product, warehouse=adjustment.warehouse).first()
                available = ws.quantity if ws else 0
                if available < adjustment.quantity:
                    messages.error(request, f'Cannot remove {adjustment.quantity}: only {available} in stock at {adjustment.warehouse}.')
                    return render(request, 'inventory/adjustment_form.html', {'form': form})

            with transaction.atomic():
                adjustment.created_by = request.user
                adjustment.save()
                services.adjust_stock(adjustment, created_by=request.user)

            messages.success(request, 'Stock adjustment recorded.')
            return redirect('inventory:adjustment_list')
    else:
        form = StockAdjustmentForm(user=request.user)
    return render(request, 'inventory/adjustment_form.html', {'form': form})
