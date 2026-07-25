from decimal import Decimal

from django import forms
from django.forms import inlineformset_factory
from inventory.models import Warehouse
from finance.models import CashRegister
from .models import Sale, SaleItem, SalesReturn, SalesReturnItem


class SaleForm(forms.ModelForm):
    amount_paid_now = forms.DecimalField(
        max_digits=14, decimal_places=2, required=False, initial=Decimal('0'),
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        label='Kitna Paisa Mila (Amount Received)',
    )
    register = forms.ModelChoiceField(
        queryset=CashRegister.objects.filter(is_active=True), required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Cash Register (Till)',
    )

    class Meta:
        model = Sale
        fields = ['customer', 'warehouse', 'invoice_no', 'date', 'discount', 'tax', 'payment_type']
        widgets = {
            'customer': forms.Select(attrs={'class': 'form-select'}),
            'warehouse': forms.Select(attrs={'class': 'form-select'}),
            'invoice_no': forms.TextInput(attrs={'class': 'form-control'}),
            'date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'discount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'tax': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'payment_type': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None and getattr(user, 'branch_id', None):
            # A branch-restricted user can only ever sell from their own
            # warehouse — no free choice, no leaking other branches' stock.
            self.fields['warehouse'].queryset = Warehouse.objects.filter(pk=user.branch_id)
            self.fields['warehouse'].initial = user.branch_id
        elif not self.initial.get('warehouse'):
            default_wh = Warehouse.objects.filter(is_default=True).first()
            if default_wh:
                self.fields['warehouse'].initial = default_wh.pk
        if not self.initial.get('register'):
            default_register = CashRegister.objects.filter(is_active=True, code='MAIN').first() \
                or CashRegister.objects.filter(is_active=True).first()
            if default_register:
                self.fields['register'].initial = default_register.pk


class SaleItemForm(forms.ModelForm):
    class Meta:
        model = SaleItem
        fields = ['product', 'quantity', 'selling_price']
        widgets = {
            'product': forms.Select(attrs={'class': 'form-select product-select'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'selling_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }


SaleItemFormSet = inlineformset_factory(
    Sale, SaleItem, form=SaleItemForm,
    extra=3, can_delete=True,
)


class SalesReturnForm(forms.ModelForm):
    class Meta:
        model = SalesReturn
        fields = ['return_no', 'date', 'note']
        widgets = {
            'return_no': forms.TextInput(attrs={'class': 'form-control'}),
            'date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'note': forms.TextInput(attrs={'class': 'form-control'}),
        }


class SalesReturnItemForm(forms.ModelForm):
    class Meta:
        model = SalesReturnItem
        fields = ['sale_item', 'quantity', 'condition']
        widgets = {
            'sale_item': forms.Select(attrs={'class': 'form-select'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'condition': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, sale=None, **kwargs):
        super().__init__(*args, **kwargs)
        if sale is not None:
            self.fields['sale_item'].queryset = sale.items.all()


SalesReturnItemFormSet = inlineformset_factory(
    SalesReturn, SalesReturnItem, form=SalesReturnItemForm,
    fields=['sale_item', 'quantity', 'condition'],
    extra=3, can_delete=True,
)
