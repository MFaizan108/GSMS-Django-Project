from decimal import Decimal

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction
from django.views.decorators.http import require_POST
from accounts.decorators import manager_required
from .models import Expense, Income, DayClosing, CashRegister
from .forms import ExpenseForm, IncomeForm, DayClosingForm, CashRegisterForm, CashTransactionForm
from . import services


@manager_required
def expense_list(request):
    expenses = Expense.objects.select_related('account').all()
    total = sum((e.amount for e in expenses), start=0)
    return render(request, 'finance/expense_list.html', {'expenses': expenses, 'total': total})


@manager_required
def expense_create(request):
    if request.method == 'POST':
        form = ExpenseForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                expense = form.save()
                services.post_expense(expense, created_by=request.user)
            messages.success(request, 'Expense added.')
            return redirect('finance:expense_list')
    else:
        form = ExpenseForm()
    return render(request, 'finance/expense_form.html', {'form': form})


@manager_required
@require_POST
def expense_delete(request, pk):
    # The Expense row is removed but its LedgerEntry/BusinessTransaction audit
    # trail is intentionally kept — ledger history is never deleted.
    get_object_or_404(Expense, pk=pk).delete()
    messages.success(request, 'Expense deleted.')
    return redirect('finance:expense_list')


@manager_required
def income_list(request):
    incomes = Income.objects.select_related('account').all()
    total = sum((i.amount for i in incomes), start=0)
    return render(request, 'finance/income_list.html', {'incomes': incomes, 'total': total})


@manager_required
def income_create(request):
    if request.method == 'POST':
        form = IncomeForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                income = form.save()
                services.post_income(income, created_by=request.user)
            messages.success(request, 'Income added.')
            return redirect('finance:income_list')
    else:
        form = IncomeForm()
    return render(request, 'finance/income_form.html', {'form': form})


@manager_required
@require_POST
def income_delete(request, pk):
    get_object_or_404(Income, pk=pk).delete()
    messages.success(request, 'Income deleted.')
    return redirect('finance:income_list')


@manager_required
def day_closing_list(request):
    closings = DayClosing.objects.all()
    return render(request, 'finance/day_closing_list.html', {'closings': closings})


@manager_required
def day_closing_detail(request, pk):
    closing = get_object_or_404(DayClosing, pk=pk)
    return render(request, 'finance/day_closing_detail.html', {'closing': closing})


@manager_required
def day_closing_create(request):
    if request.method == 'POST':
        form = DayClosingForm(request.POST)
        if form.is_valid():
            closing = services.close_day(
                date=form.cleaned_data['date'],
                opening_cash=form.cleaned_data['opening_cash'],
                actual_cash=form.cleaned_data['actual_cash'],
                withdrawals=form.cleaned_data.get('withdrawals') or Decimal('0'),
                note=form.cleaned_data.get('note', ''),
                user=request.user,
            )
            messages.success(request, f'Day closed. Difference: {closing.difference}')
            return redirect('finance:day_closing_detail', pk=closing.pk)
    else:
        last = DayClosing.objects.order_by('-date').first()
        initial = {}
        if last:
            initial['opening_cash'] = last.actual_cash
        form = DayClosingForm(initial=initial)
    return render(request, 'finance/day_closing_form.html', {'form': form})


@manager_required
def cash_register_list(request):
    registers = CashRegister.objects.select_related('warehouse').all()
    return render(request, 'finance/cash_register_list.html', {'registers': registers})


@manager_required
def cash_register_create(request):
    if request.method == 'POST':
        form = CashRegisterForm(request.POST)
        if form.is_valid():
            register = form.save()
            services.get_or_create_register_account(register)
            messages.success(request, 'Cash register created.')
            return redirect('finance:cash_register_list')
    else:
        form = CashRegisterForm()
    return render(request, 'finance/cash_register_form.html', {'form': form})


@manager_required
def cash_register_detail(request, pk):
    register = get_object_or_404(CashRegister, pk=pk)
    transactions = register.transactions.all()[:100]
    form = CashTransactionForm()
    return render(request, 'finance/cash_register_detail.html', {
        'register': register, 'transactions': transactions, 'form': form,
    })


@manager_required
@require_POST
def cash_transaction_create(request, pk):
    register = get_object_or_404(CashRegister, pk=pk)
    form = CashTransactionForm(request.POST)
    if form.is_valid():
        services.record_cash_transaction(
            register=register, transaction_type=form.cleaned_data['transaction_type'],
            direction=form.direction(), amount=form.cleaned_data['amount'],
            note=form.cleaned_data.get('note', ''), user=request.user,
        )
        messages.success(request, 'Cash transaction recorded.')
    else:
        messages.error(request, 'Could not record transaction — check the amount.')
    return redirect('finance:cash_register_detail', pk=pk)
