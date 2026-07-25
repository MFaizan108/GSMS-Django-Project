from .models import AuditLog


def log_action(user, action, module, obj, old_data=None, new_data=None, ip_address=None):
    AuditLog.objects.create(
        user=user, action=action, module=module,
        object_type=obj.__class__.__name__, object_id=getattr(obj, 'pk', None),
        object_repr=str(obj)[:255],
        old_data=old_data, new_data=new_data, ip_address=ip_address,
    )
