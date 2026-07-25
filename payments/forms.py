from django import forms
from django.utils import timezone
from finance.models import Account


class AllocationHeaderForm(forms.Form):
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


class InvoiceAllocationForm(forms.Form):
    invoice_id = forms.IntegerField(widget=forms.HiddenInput())
    amount = forms.DecimalField(
        max_digits=14, decimal_places=2, required=False, min_value=0,
        widget=forms.NumberInput(attrs={'class': 'form-control form-control-sm', 'step': '0.01'}),
    )


InvoiceAllocationFormSet = forms.formset_factory(InvoiceAllocationForm, extra=0)
