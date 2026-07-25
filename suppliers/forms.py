from decimal import Decimal

from django import forms
from django.core.validators import MinValueValidator
from finance.models import CashRegister
from .models import Supplier


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ['name', 'company', 'phone', 'cnic', 'email', 'address', 'opening_balance']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'company': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'cnic': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'opening_balance': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }


class SupplierPaymentForm(forms.Form):
    amount = forms.DecimalField(
        max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))],
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
    )
    description = forms.CharField(max_length=255, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    register = forms.ModelChoiceField(
        queryset=CashRegister.objects.filter(is_active=True), required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Cash Register (Till)',
    )


class BalanceAdjustmentForm(forms.Form):
    """The one controlled way to manually correct a supplier's ledger
    balance — see finance.services.post_balance_adjustment. `amount` can be
    positive (increase what's owed to the supplier) or negative (decrease
    it), but never zero, and a note is mandatory so the adjustment is always
    explained on the ledger."""
    amount = forms.DecimalField(
        max_digits=14, decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        help_text='Positive increases the balance owed; negative decreases it.',
    )
    note = forms.CharField(max_length=255, widget=forms.TextInput(attrs={'class': 'form-control'}))

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount == 0:
            raise forms.ValidationError('Adjustment amount cannot be zero.')
        return amount
