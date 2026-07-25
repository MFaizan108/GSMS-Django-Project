from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = 'admin', 'Admin'
        MANAGER = 'manager', 'Manager'
        CASHIER = 'cashier', 'Cashier'

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CASHIER)
    phone = models.CharField(max_length=20, blank=True)
    photo = models.ImageField(upload_to='users/', null=True, blank=True)
    # If set, this user is restricted to this one warehouse/branch — see
    # inventory.services.get_allowed_warehouses. Left blank (the default) for
    # admins/owners who need to see and work across every branch.
    branch = models.ForeignKey('inventory.Warehouse', on_delete=models.SET_NULL, null=True, blank=True, related_name='staff')

    def is_admin(self):
        return self.role == self.Role.ADMIN or self.is_superuser

    def is_manager(self):
        return self.role in (self.Role.ADMIN, self.Role.MANAGER) or self.is_superuser

    def is_cashier(self):
        return self.role == self.Role.CASHIER

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"
