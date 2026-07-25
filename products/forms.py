from django import forms
from masters.models import PriceLevel
from .models import Category, Brand, Unit, Product, ProductPrice


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }


class BrandForm(forms.ModelForm):
    class Meta:
        model = Brand
        fields = ['name']
        widgets = {'name': forms.TextInput(attrs={'class': 'form-control'})}


class UnitForm(forms.ModelForm):
    class Meta:
        model = Unit
        fields = ['name', 'short_name']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'short_name': forms.TextInput(attrs={'class': 'form-control'}),
        }


class ProductForm(forms.ModelForm):
    retail_price = forms.DecimalField(
        max_digits=12, decimal_places=2, required=True,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
    )
    wholesale_price = forms.DecimalField(
        max_digits=12, decimal_places=2, required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
    )
    special_price = forms.DecimalField(
        max_digits=12, decimal_places=2, required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
    )

    class Meta:
        model = Product
        fields = [
            'name', 'barcode', 'sku', 'category', 'brand', 'unit', 'tax',
            'purchase_price', 'minimum_stock', 'expiry_date', 'manufacture_date',
            'image', 'description', 'status',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'barcode': forms.TextInput(attrs={'class': 'form-control'}),
            'sku': forms.TextInput(attrs={'class': 'form-control'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'brand': forms.Select(attrs={'class': 'form-select'}),
            'unit': forms.Select(attrs={'class': 'form-select'}),
            'tax': forms.Select(attrs={'class': 'form-select'}),
            'purchase_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'minimum_stock': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'expiry_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'manufacture_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'status': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._user = user
        if self.instance.pk:
            for level_name, field_name in [('Retail', 'retail_price'), ('Wholesale', 'wholesale_price'), ('Special', 'special_price')]:
                price = self.instance.price_for(level_name)
                if price is not None:
                    self.fields[field_name].initial = price

    def save(self, commit=True):
        product = super().save(commit=commit)
        if commit:
            self._save_prices(product)
        return product

    def _save_prices(self, product):
        from audit import services as audit_services
        from audit.models import AuditLog

        for level_name, field_name in [('Retail', 'retail_price'), ('Wholesale', 'wholesale_price'), ('Special', 'special_price')]:
            value = self.cleaned_data.get(field_name)
            if value in (None, ''):
                continue
            level, _ = PriceLevel.objects.get_or_create(name=level_name)
            old_price = product.price_for(level_name)
            _, created = ProductPrice.objects.update_or_create(product=product, price_level=level, defaults={'price': value})
            if not created and old_price is not None and old_price != value:
                audit_services.log_action(
                    self._user, AuditLog.Action.PRICE_CHANGE, 'products', product,
                    old_data={level_name: str(old_price)}, new_data={level_name: str(value)},
                )
