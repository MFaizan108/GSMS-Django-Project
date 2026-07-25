from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'first_name', 'last_name', 'role', 'is_active')
    fieldsets = UserAdmin.fieldsets + (
        ('GSMS Info', {'fields': ('role', 'phone')}),
    )
