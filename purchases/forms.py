from decimal import Decimal

from django import forms
from django.forms import inlineformset_factory
from inventory.models import Warehouse
from finance.models import CashRegister
from .models import Purchase, PurchaseItem, PurchaseReturn, PurchaseReturnItem, PurchaseOrder, PurchaseOrderItem


class PurchaseForm(forms.ModelForm):
    amount_paid_now = forms.DecimalField(
        max_digits=14, decimal_places=2, required=False, initial=Decimal('0'),
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        label='Amount Paid Now',
    )
    register = forms.ModelChoiceField(
        queryset=CashRegister.objects.filter(is_active=True), required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Cash Register (Till)',
    )

    class Meta:
        model = Purchase
        fields = ['supplier', 'warehouse', 'invoice_no', 'date', 'discount', 'tax']
        widgets = {
            'supplier': forms.Select(attrs={'class': 'form-select'}),
            'warehouse': forms.Select(attrs={'class': 'form-select'}),
            'invoice_no': forms.TextInput(attrs={'class': 'form-control'}),
            'date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'discount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'tax': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None and getattr(user, 'branch_id', None):
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


class PurchaseItemForm(forms.ModelForm):
    batch_number = forms.CharField(
        max_length=50, required=False, widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    # Set when a row is pre-filled from a PurchaseOrderItem (see purchase_create's
    # ?from_po= flow) so create_purchase() can link the resulting PurchaseItem
    # back to it and update the order's fulfillment status.
    purchase_order_item_id = forms.IntegerField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = PurchaseItem
        fields = ['product', 'quantity', 'purchase_price', 'expiry_date']
        widgets = {
            'product': forms.Select(attrs={'class': 'form-select product-select'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'purchase_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'expiry_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }


PurchaseItemFormSet = inlineformset_factory(
    Purchase, PurchaseItem, form=PurchaseItemForm,
    extra=3, can_delete=True,
)


class PurchaseReturnForm(forms.ModelForm):
    class Meta:
        model = PurchaseReturn
        fields = ['return_no', 'date', 'note']
        widgets = {
            'return_no': forms.TextInput(attrs={'class': 'form-control'}),
            'date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'note': forms.TextInput(attrs={'class': 'form-control'}),
        }


class PurchaseReturnItemForm(forms.ModelForm):
    class Meta:
        model = PurchaseReturnItem
        fields = ['purchase_item', 'quantity']
        widgets = {
            'purchase_item': forms.Select(attrs={'class': 'form-select'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }

    def __init__(self, *args, purchase=None, **kwargs):
        super().__init__(*args, **kwargs)
        if purchase is not None:
            self.fields['purchase_item'].queryset = purchase.items.all()


PurchaseReturnItemFormSet = inlineformset_factory(
    PurchaseReturn, PurchaseReturnItem, form=PurchaseReturnItemForm,
    fields=['purchase_item', 'quantity'],
    extra=3, can_delete=True,
)


class PurchaseOrderForm(forms.ModelForm):
    class Meta:
        model = PurchaseOrder
        fields = ['supplier', 'warehouse', 'order_no', 'date', 'note']
        widgets = {
            'supplier': forms.Select(attrs={'class': 'form-select'}),
            'warehouse': forms.Select(attrs={'class': 'form-select'}),
            'order_no': forms.TextInput(attrs={'class': 'form-control'}),
            'date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'note': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None and getattr(user, 'branch_id', None):
            self.fields['warehouse'].queryset = Warehouse.objects.filter(pk=user.branch_id)
            self.fields['warehouse'].initial = user.branch_id
        elif not self.initial.get('warehouse'):
            default_wh = Warehouse.objects.filter(is_default=True).first()
            if default_wh:
                self.fields['warehouse'].initial = default_wh.pk


class PurchaseOrderItemForm(forms.ModelForm):
    class Meta:
        model = PurchaseOrderItem
        fields = ['product', 'quantity', 'expected_price']
        widgets = {
            'product': forms.Select(attrs={'class': 'form-select product-select'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'expected_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }


PurchaseOrderItemFormSet = inlineformset_factory(
    PurchaseOrder, PurchaseOrderItem, form=PurchaseOrderItemForm,
    extra=3, can_delete=True,
)
