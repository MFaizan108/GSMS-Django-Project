from django import forms
from .models import StockAdjustment
from .services import get_allowed_warehouses


class StockAdjustmentForm(forms.ModelForm):
    unit_cost = forms.DecimalField(
        max_digits=12, decimal_places=2, required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        label='Unit Cost (increase only — leave blank to use product default)',
    )

    class Meta:
        model = StockAdjustment
        fields = ['product', 'warehouse', 'adjust_type', 'quantity', 'unit_cost', 'reason', 'note']
        widgets = {
            'product': forms.Select(attrs={'class': 'form-select'}),
            'warehouse': forms.Select(attrs={'class': 'form-select'}),
            'adjust_type': forms.Select(attrs={'class': 'form-select'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'reason': forms.Select(attrs={'class': 'form-select'}),
            'note': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields['warehouse'].queryset = get_allowed_warehouses(user)
            if getattr(user, 'branch_id', None):
                self.fields['warehouse'].initial = user.branch_id
