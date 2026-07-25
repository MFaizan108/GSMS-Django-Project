from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def role_required(*roles):
    """Allow access only to users whose role is in `roles` (superusers always allowed)."""
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def _wrapped(request, *args, **kwargs):
            user = request.user
            if user.is_superuser or user.role in roles:
                return view_func(request, *args, **kwargs)
            raise PermissionDenied("You do not have permission to access this page.")
        return _wrapped
    return decorator


def admin_required(view_func):
    return role_required('admin')(view_func)


def manager_required(view_func):
    return role_required('admin', 'manager')(view_func)


def cashier_required(view_func):
    return role_required('admin', 'manager', 'cashier')(view_func)
