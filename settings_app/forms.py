from django import forms
from .models import StoreSettings


class StoreSettingsForm(forms.ModelForm):
    smtp_password = forms.CharField(
        required=False, widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}, render_value=True),
        help_text='Leave blank to keep the current password unchanged.',
    )
    brevo_api_key = forms.CharField(
        required=False, widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}, render_value=True),
        help_text='From brevo.com (Settings → SMTP & API → API Keys). Used instead of SMTP below when set.',
    )

    class Meta:
        model = StoreSettings
        fields = [
            'store_name', 'owner_name', 'phone', 'address', 'logo', 'invoice_footer', 'tax_percent', 'currency',
            'brevo_api_key', 'smtp_host', 'smtp_port', 'smtp_username', 'smtp_password', 'smtp_use_tls', 'from_email',
        ]
        widgets = {
            'store_name': forms.TextInput(attrs={'class': 'form-control'}),
            'owner_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'invoice_footer': forms.TextInput(attrs={'class': 'form-control'}),
            'tax_percent': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'currency': forms.TextInput(attrs={'class': 'form-control'}),
            'smtp_host': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'smtp.gmail.com'}),
            'smtp_port': forms.NumberInput(attrs={'class': 'form-control'}),
            'smtp_username': forms.TextInput(attrs={'class': 'form-control'}),
            'smtp_use_tls': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'from_email': forms.EmailInput(attrs={'class': 'form-control'}),
        }
