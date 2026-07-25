from decimal import Decimal

from django.utils import timezone
from django import forms
from django.core.validators import MinValueValidator
from .models import Account, Expense, Income, DayClosing, CashRegister, CashTransaction


class PaymentEntryForm(forms.Form):
    """Reusable "record a payment against this invoice" form used by both
    purchases and sales add-payment views."""
    amount = forms.DecimalField(
        max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))],
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
    )
    account = forms.ModelChoiceField(
        queryset=Account.objects.none(), widget=forms.Select(attrs={'class': 'form-select'}),
    )
    date = forms.DateField(
        initial=timezone.localdate, widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    note = forms.CharField(max_length=255, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['account'].queryset = Account.objects.filter(subtype__in=Account.PAYMENT_SUBTYPES)
        cash = self.fields['account'].queryset.filter(code='1000').first()
        if cash:
            self.fields['account'].initial = cash.pk


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ['title', 'amount', 'date', 'account', 'description']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'account': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['account'].queryset = Account.objects.filter(subtype__in=Account.PAYMENT_SUBTYPES)
        if not self.initial.get('account'):
            cash = self.fields['account'].queryset.filter(code='1000').first()
            if cash:
                self.fields['account'].initial = cash.pk


class DayClosingForm(forms.Form):
    date = forms.DateField(
        initial=timezone.localdate, widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    opening_cash = forms.DecimalField(
        max_digits=14, decimal_places=2, widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
    )
    withdrawals = forms.DecimalField(
        max_digits=14, decimal_places=2, required=False, initial=0,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
    )
    actual_cash = forms.DecimalField(
        max_digits=14, decimal_places=2, widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        label='Actual Cash Counted',
    )
    note = forms.CharField(max_length=255, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))


class CashRegisterForm(forms.ModelForm):
    class Meta:
        model = CashRegister
        fields = ['name', 'code', 'warehouse', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'warehouse': forms.Select(attrs={'class': 'form-select'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class CashTransactionForm(forms.Form):
    transaction_type = forms.ChoiceField(
        choices=CashTransaction.Type.choices, widget=forms.Select(attrs={'class': 'form-select'}),
    )
    amount = forms.DecimalField(
        max_digits=14, decimal_places=2, widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
    )
    note = forms.CharField(max_length=255, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))

    DIRECTION_BY_TYPE = {
        CashTransaction.Type.OPENING_FLOAT: CashTransaction.Direction.IN,
        CashTransaction.Type.OWNER_FUNDING: CashTransaction.Direction.IN,
        CashTransaction.Type.OWNER_WITHDRAWAL: CashTransaction.Direction.OUT,
        CashTransaction.Type.BANK_TO_REGISTER: CashTransaction.Direction.IN,
        CashTransaction.Type.REGISTER_TO_BANK: CashTransaction.Direction.OUT,
        CashTransaction.Type.SAFE_TO_REGISTER: CashTransaction.Direction.IN,
        CashTransaction.Type.REGISTER_TO_SAFE: CashTransaction.Direction.OUT,
    }

    def direction(self):
        return self.DIRECTION_BY_TYPE[self.cleaned_data['transaction_type']]


class IncomeForm(forms.ModelForm):
    class Meta:
        model = Income
        fields = ['title', 'amount', 'date', 'account', 'description']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'account': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['account'].queryset = Account.objects.filter(subtype__in=Account.PAYMENT_SUBTYPES)
        if not self.initial.get('account'):
            cash = self.fields['account'].queryset.filter(code='1000').first()
            if cash:
                self.fields['account'].initial = cash.pk
