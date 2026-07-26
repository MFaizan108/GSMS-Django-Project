from django.shortcuts import render, redirect
from django.contrib import messages
from accounts.decorators import admin_required
from .models import StoreSettings
from .forms import StoreSettingsForm


@admin_required
def store_settings_view(request):
    settings_obj = StoreSettings.get_solo()
    if request.method == 'POST':
        form = StoreSettingsForm(request.POST, request.FILES, instance=settings_obj)
        if form.is_valid():
            store = form.save(commit=False)
            if not form.cleaned_data.get('smtp_password'):
                store.smtp_password = settings_obj.smtp_password
            if not form.cleaned_data.get('brevo_api_key'):
                store.brevo_api_key = settings_obj.brevo_api_key
            store.save()
            messages.success(request, 'Settings updated.')
            return redirect('settings_app:store_settings')
    else:
        form = StoreSettingsForm(instance=settings_obj)
    return render(request, 'settings_app/store_settings.html', {'form': form})
