from decimal import Decimal

from django.test import TestCase

from audit.models import AuditLog
from customers.models import Customer
from suppliers.models import Supplier
from inventory.models import Warehouse
from sales.models import Sale
from purchases.models import Purchase
from .models import User


class LoginAuditTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='login_audit_user', password='correct-pw', role=User.Role.ADMIN)

    def test_failed_login_is_logged(self):
        self.client.post('/accounts/login/', {'username': 'login_audit_user', 'password': 'wrong-pw'})
        self.assertTrue(
            AuditLog.objects.filter(action=AuditLog.Action.FAILED_LOGIN, object_repr='login_audit_user').exists()
        )

    def test_successful_login_is_logged(self):
        self.client.post('/accounts/login/', {'username': 'login_audit_user', 'password': 'correct-pw'})
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.LOGIN, object_id=self.user.pk).exists())

    def test_logout_is_logged(self):
        self.client.force_login(self.user)
        self.client.post('/accounts/logout/')
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.LOGOUT, object_id=self.user.pk).exists())


class RoleChangeAuditTests(TestCase):
    def test_role_change_is_logged_distinctly_from_a_plain_update(self):
        admin = User.objects.create_user(username='role_audit_admin', password='x', role=User.Role.ADMIN)
        target = User.objects.create_user(username='role_audit_target', password='x', role=User.Role.CASHIER)
        self.client.force_login(admin)

        self.client.post(f'/accounts/users/{target.pk}/edit/', {
            'username': target.username, 'first_name': '', 'last_name': '', 'email': '', 'phone': '',
            'role': User.Role.MANAGER, 'is_active': 'on',
        })

        target.refresh_from_db()
        self.assertEqual(target.role, User.Role.MANAGER)
        entry = AuditLog.objects.filter(action=AuditLog.Action.ROLE_CHANGE, object_id=target.pk).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.old_data, {'role': 'cashier'})
        self.assertEqual(entry.new_data, {'role': 'manager'})


class OutgoingMoneyPermissionTests(TestCase):
    """Anyone can take money in (that's the cashier's job); only a manager
    can send money back out to a supplier or customer — a cashier acting
    alone shouldn't be able to pay a supplier or refund a customer."""

    def setUp(self):
        self.cashier = User.objects.create_user(username='perm_cashier', password='x', role=User.Role.CASHIER)
        self.manager = User.objects.create_user(username='perm_manager', password='x', role=User.Role.MANAGER)
        self.supplier = Supplier.objects.create(name='Permission Test Supplier')
        self.customer = Customer.objects.create(name='Permission Test Customer')

    def test_cashier_cannot_pay_supplier(self):
        self.client.force_login(self.cashier)
        resp = self.client.post(f'/suppliers/{self.supplier.pk}/payment/', {'amount': '10', 'description': ''})
        self.assertEqual(resp.status_code, 403)

    def test_manager_can_pay_supplier(self):
        self.client.force_login(self.manager)
        resp = self.client.post(f'/suppliers/{self.supplier.pk}/payment/', {'amount': '10', 'description': ''})
        self.assertEqual(resp.status_code, 302)

    def test_cashier_cannot_refund_customer(self):
        self.client.force_login(self.cashier)
        resp = self.client.post(f'/customers/{self.customer.pk}/give-payment/', {'amount': '10', 'description': ''})
        self.assertEqual(resp.status_code, 403)

    def test_cashier_can_still_receive_customer_payment(self):
        self.client.force_login(self.cashier)
        resp = self.client.post(f'/customers/{self.customer.pk}/payment/', {'amount': '10', 'description': ''})
        self.assertEqual(resp.status_code, 302, "receiving payment IN is a normal cashier task and must still work")

    def test_cashier_cannot_use_refund_direction_on_the_ajax_endpoint(self):
        self.client.force_login(self.cashier)
        resp = self.client.post(f'/customers/{self.customer.pk}/record-payment/', {'amount': '10', 'direction': 'out'})
        self.assertEqual(resp.status_code, 403)


class BranchRestrictionTests(TestCase):
    """A user with `branch` set must only see/act on their own warehouse's
    Sales and Purchases; a user with no branch (admin/owner) sees everything."""

    def setUp(self):
        self.branch_a = Warehouse.objects.create(name='Branch A', code='T-BRANCH-A')
        self.branch_b = Warehouse.objects.create(name='Branch B', code='T-BRANCH-B')
        self.restricted_user = User.objects.create_user(
            username='branch_a_cashier', password='x', role=User.Role.CASHIER, branch=self.branch_a,
        )
        self.unrestricted_admin = User.objects.create_user(username='branch_admin', password='x', role=User.Role.ADMIN)

        Sale.objects.create(invoice_no='T-BR-SALE-A', warehouse=self.branch_a, date='2026-07-25', total=Decimal('100'))
        Sale.objects.create(invoice_no='T-BR-SALE-B', warehouse=self.branch_b, date='2026-07-25', total=Decimal('200'))
        Purchase.objects.create(
            invoice_no='T-BR-PUR-A', warehouse=self.branch_a,
            supplier=Supplier.objects.create(name='Branch Test Supplier'), date='2026-07-25', total=Decimal('50'),
        )

    def test_restricted_user_only_sees_their_branch_sales(self):
        self.client.force_login(self.restricted_user)
        resp = self.client.get('/sales/')
        invoices = {s.invoice_no for s in resp.context['sales']}
        self.assertEqual(invoices, {'T-BR-SALE-A'})

    def test_unrestricted_admin_sees_all_branches_sales(self):
        self.client.force_login(self.unrestricted_admin)
        resp = self.client.get('/sales/')
        invoices = {s.invoice_no for s in resp.context['sales']}
        self.assertEqual(invoices, {'T-BR-SALE-A', 'T-BR-SALE-B'})

    def test_restricted_user_only_sees_their_branch_purchases(self):
        self.client.force_login(self.restricted_user)
        resp = self.client.get('/purchases/')
        invoices = {p.invoice_no for p in resp.context['purchases']}
        self.assertEqual(invoices, {'T-BR-PUR-A'})

    def test_sale_form_locks_warehouse_choice_for_restricted_user(self):
        from sales.forms import SaleForm
        form = SaleForm(user=self.restricted_user)
        choices = list(form.fields['warehouse'].queryset)
        self.assertEqual(choices, [self.branch_a])
        self.assertEqual(form.fields['warehouse'].initial, self.branch_a.pk)

    def test_sale_form_allows_all_warehouses_for_unrestricted_user(self):
        from sales.forms import SaleForm
        form = SaleForm(user=self.unrestricted_admin)
        choices = set(form.fields['warehouse'].queryset)
        self.assertEqual(choices, {self.branch_a, self.branch_b} | set(Warehouse.objects.exclude(pk__in=[self.branch_a.pk, self.branch_b.pk])))
