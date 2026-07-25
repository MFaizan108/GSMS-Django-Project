from decimal import Decimal

from django.test import TestCase
from django.db.models import Sum

from .models import Account, CashRegister, CashTransaction, LedgerEntry, Payment
from . import services


class CashRegisterGLRoutingTests(TestCase):
    """Each CashTransaction.Type must post against its own correct
    counter-account — the P0 bug was every type (deposit, withdrawal, cash
    drop) hitting the same generic Owner Capital account regardless of what
    actually happened."""

    def setUp(self):
        account = Account.objects.create(code='TEST-REG', name='Test Register Cash', type=Account.Type.ASSET, subtype=Account.Subtype.CASH)
        self.register = CashRegister.objects.create(name='Test Register', code='TEST-REG', linked_account=account)

    def _balance(self, code):
        return Account.objects.get(code=code).balance

    def test_owner_funding_hits_owner_capital(self):
        before = self._balance('3200')
        services.record_cash_transaction(self.register, CashTransaction.Type.OWNER_FUNDING, CashTransaction.Direction.IN, Decimal('100'), '', None)
        self.assertEqual(self._balance('3200'), before + Decimal('100'))

    def test_cash_drop_hits_safe_not_owner_capital(self):
        services.record_cash_transaction(self.register, CashTransaction.Type.OWNER_FUNDING, CashTransaction.Direction.IN, Decimal('200'), '', None)
        owner_capital_before = self._balance('3200')
        safe_before = self._balance('1005')

        services.record_cash_transaction(self.register, CashTransaction.Type.REGISTER_TO_SAFE, CashTransaction.Direction.OUT, Decimal('50'), '', None)

        self.assertEqual(self._balance('3200'), owner_capital_before, "cash drop must not touch Owner Capital")
        self.assertEqual(self._balance('1005'), safe_before + Decimal('50'))

    def test_bank_transfer_hits_bank_account(self):
        services.record_cash_transaction(self.register, CashTransaction.Type.OWNER_FUNDING, CashTransaction.Direction.IN, Decimal('200'), '', None)
        bank_before = self._balance('1010')
        services.record_cash_transaction(self.register, CashTransaction.Type.REGISTER_TO_BANK, CashTransaction.Direction.OUT, Decimal('75'), '', None)
        self.assertEqual(self._balance('1010'), bank_before + Decimal('75'))


class AccountReconciliationTests(TestCase):
    """Account.balance (a cache) must always equal the signed sum of that
    account's real LedgerEntry rows — the invariant reports.account_reconciliation_report checks."""

    def test_all_seeded_accounts_reconcile_after_activity(self):
        account = Account.objects.create(code='TEST-REG2', name='Test Register 2', type=Account.Type.ASSET, subtype=Account.Subtype.CASH)
        register = CashRegister.objects.create(name='Test Register 2', code='TEST-REG2', linked_account=account)
        services.record_cash_transaction(register, CashTransaction.Type.OWNER_FUNDING, CashTransaction.Direction.IN, Decimal('300'), '', None)
        services.record_cash_transaction(register, CashTransaction.Type.REGISTER_TO_SAFE, CashTransaction.Direction.OUT, Decimal('120'), '', None)

        for acc in Account.objects.all():
            debit_total = acc.entries.filter(entry_type=LedgerEntry.EntryType.DEBIT).aggregate(t=Sum('amount'))['t'] or Decimal('0')
            credit_total = acc.entries.filter(entry_type=LedgerEntry.EntryType.CREDIT).aggregate(t=Sum('amount'))['t'] or Decimal('0')
            computed = (debit_total - credit_total) if acc.type in Account.DEBIT_INCREASES else (credit_total - debit_total)
            self.assertEqual(acc.balance, computed, f"{acc.code} ({acc.name}) does not reconcile")


class CashRegisterTaggingTests(TestCase):
    """Sale/Payment rows tagged to a specific CashRegister must route their
    actual cash leg to that register's own linked_account, so a second
    till's balance stops being frozen at manual float top-ups only — the
    P1 #9 gap. Untagged (register=None) calls must behave exactly as before."""

    def setUp(self):
        second_account = Account.objects.create(
            code='TEST-REG9', name='Second Till Cash', type=Account.Type.ASSET, subtype=Account.Subtype.CASH,
        )
        self.second_register = CashRegister.objects.create(name='Second Till', code='TEST-REG9', linked_account=second_account)
        self.main_cash_account = Account.objects.get(code='1000')

    def test_walkin_sale_tagged_to_second_register_credits_its_own_account(self):
        from products.models import Category, Brand, Unit, Product
        from inventory.models import Warehouse
        from inventory import services as inv_services
        from sales.models import Sale
        from sales import services as sales_services

        category = Category.objects.create(name='Register Tag Category')
        brand = Brand.objects.create(name='Register Tag Brand')
        unit = Unit.objects.create(name='Piece RT', short_name='pc')
        product = Product.objects.create(name='Register Tag Product', category=category, brand=brand, unit=unit, purchase_price=Decimal('10'))
        warehouse = Warehouse.objects.filter(is_default=True).first() or Warehouse.objects.first()
        inv_services.receive_stock(product=product, warehouse=warehouse, quantity=Decimal('10'), unit_cost=Decimal('10'))

        main_before = self.main_cash_account.balance
        second_before = self.second_register.current_balance

        sale = Sale(customer=None, warehouse=warehouse, invoice_no='T-SALE-REG9', date='2026-07-25')
        sale = sales_services.create_sale(
            sale, [{'product': product, 'quantity': Decimal('1'), 'selling_price': Decimal('50')}], Decimal('50'),
            None, register=self.second_register,
        )
        sale.refresh_from_db()

        self.assertEqual(sale.register_id, self.second_register.pk)
        self.assertEqual(self.second_register.current_balance, second_before + Decimal('50'))
        self.assertEqual(Account.objects.get(code='1000').balance, main_before, "MAIN's account must be untouched")

    def test_walkin_sale_without_register_still_hits_main_cash_account(self):
        from products.models import Category, Brand, Unit, Product
        from inventory.models import Warehouse
        from inventory import services as inv_services
        from sales.models import Sale
        from sales import services as sales_services

        category = Category.objects.create(name='Register Tag Category 2')
        brand = Brand.objects.create(name='Register Tag Brand 2')
        unit = Unit.objects.create(name='Piece RT2', short_name='pc')
        product = Product.objects.create(name='Register Tag Product 2', category=category, brand=brand, unit=unit, purchase_price=Decimal('10'))
        warehouse = Warehouse.objects.filter(is_default=True).first() or Warehouse.objects.first()
        inv_services.receive_stock(product=product, warehouse=warehouse, quantity=Decimal('10'), unit_cost=Decimal('10'))

        main_before = Account.objects.get(code='1000').balance

        sale = Sale(customer=None, warehouse=warehouse, invoice_no='T-SALE-NOREG', date='2026-07-25')
        sale = sales_services.create_sale(
            sale, [{'product': product, 'quantity': Decimal('1'), 'selling_price': Decimal('30')}], Decimal('30'), None,
        )
        sale.refresh_from_db()

        self.assertIsNone(sale.register_id)
        self.assertEqual(Account.objects.get(code='1000').balance, main_before + Decimal('30'))

    def test_customer_payment_tagged_to_second_register(self):
        from customers.models import Customer
        customer = Customer.objects.create(name='Register Tag Customer')

        second_before = self.second_register.current_balance
        payment = services.record_payment(
            Payment.Direction.IN, Decimal('75'), self.main_cash_account, '2026-07-25',
            customer=customer, note='Tagged to second till', register=self.second_register,
        )

        self.assertEqual(payment.register_id, self.second_register.pk)
        self.assertEqual(payment.account_id, self.second_register.linked_account_id, 'register must override the passed-in account')
        self.assertEqual(self.second_register.current_balance, second_before + Decimal('75'))

    def test_customer_payment_without_register_hits_the_passed_account(self):
        from customers.models import Customer
        customer = Customer.objects.create(name='Register Tag Customer 2')

        main_before = Account.objects.get(code='1000').balance
        payment = services.record_payment(
            Payment.Direction.IN, Decimal('40'), self.main_cash_account, '2026-07-25',
            customer=customer, note='Untagged',
        )

        self.assertIsNone(payment.register_id)
        self.assertEqual(payment.account_id, self.main_cash_account.pk)
        self.assertEqual(Account.objects.get(code='1000').balance, main_before + Decimal('40'))
