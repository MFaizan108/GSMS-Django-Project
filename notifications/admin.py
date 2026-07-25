from django.contrib import admin
from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('title', 'type', 'level', 'is_read', 'created_at')
    list_filter = ('type', 'level', 'is_read')

    def has_add_permission(self, request):
        return False
