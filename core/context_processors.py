def store_settings(request):
    try:
        from settings_app.models import StoreSettings
        settings_obj = StoreSettings.get_solo()
    except Exception:
        settings_obj = None
    return {'store_settings': settings_obj}


def unread_notifications(request):
    if not request.user.is_authenticated:
        return {}
    from notifications.models import Notification
    return {'unread_notifications_count': Notification.objects.filter(is_read=False).count()}
