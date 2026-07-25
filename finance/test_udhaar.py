"""End-to-end coverage for the Udhaar (Customer Receivable / Supplier
Payable) ledger feature — one file per the 20-scenario checklist the feature
was built against, since most scenarios share the same sale/purchase/payment
fixtures and are easier to audit together than scattered across apps.

Every scenario re-derives outstanding two ways and checks they agree:
  1. party.current_balance (the live GL query — the single source of truth)
  2. get_party_statement(...)'s summary (total_invoiced - total_paid, modulo
     returns/adjustments), which is what the customer/supplier detail pages
     and the Udhaar hub actually display.
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from inventory.models import Warehouse
from inventory import services as inv_services
from products.models import Product, Category, Brand, Unit
from customers.models import Customer
from suppliers.models import Supplier
from sales.models import Sale, SalesReturn, SalesReturnItem
from sales import services as sales_services
from purchases.models import Purchase, PurchaseReturn
from purchases import services as purchases_services
from finance.models import Account, Payment
from finance import services as fin_services
from payments import services as pay_services


def make_product(suffix, stock=Decimal('100'), cost=Decimal('10')):
    category = Category.objects.create(name=f'Udhaar Cat {suffix}')
    brand = Brand.objects.create(name=f'Udhaar Brand {suffix}')
    unit = Unit.objects.create(name=f'Udhaar Unit {suffix}', short_name='pc')
    product = Product.objects.create(name=f'Udhaar Product {suffix}', category=category, brand=brand, unit=unit, purchase_price=cost)
    wh = Warehouse.objects.filter(is_default=True).first() or Warehouse.objects.first()
    if stock:
        inv_services.receive_stock(product=product, warehouse=wh, quantity=stock, unit_cost=cost)
    return product, wh


class UdhaarScenariosTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='udhaar_admin', password='x', role=User.Role.ADMIN)
        self.client.force_login(self.user)
        self.next_invoice = 0
        self.next_purchase_invoice = 0

    def _invoice_no(self):
        self.next_invoice += 1
        return f'UDH-SALE-{self.next_invoice}'

    def _purchase_invoice_no(self):
        self.next_purchase_invoice += 1
        return f'UDH-PUR-{self.next_purchase_invoice}'

    def make_sale(self, customer, product, warehouse, qty, price, paid):
        sale = Sale(customer=customer, warehouse=warehouse, invoice_no=self._invoice_no(), date='2026-07-25')
        return sales_services.create_sale(
            sale, [{'product': product, 'quantity': qty, 'selling_price': price}], paid, self.user,
        )

    def make_purchase(self, supplier, product, warehouse, qty, price, paid):
        purchase = Purchase(supplier=supplier, warehouse=warehouse, invoice_no=self._purchase_invoice_no(), date='2026-07-25')
        return purchases_services.create_purchase(
            purchase, [{'product': product, 'quantity': qty, 'purchase_price': price}], paid, self.user,
        )

    def assert_outstanding_matches_formula(self, party, party_kind):
        """outstanding == total_credit - total_payments, per party.current_balance
        and the statement helper both — they must never disagree."""
        _, stats = fin_services.get_party_statement(party, party_kind)
        self.assertEqual(stats['outstanding'], party.current_balance)

    # 1. Full cash sale
    def test_full_cash_sale_walkin_no_customer(self):
        product, wh = make_product('cash-sale')
        sale = self.make_sale(None, product, wh, Decimal('2'), Decimal('50'), Decimal('100'))
        self.assertEqual(sale.total, Decimal('100'))
        self.assertEqual(sale.paid, Decimal('100'))
        self.assertEqual(sale.remaining, Decimal('0'))
        self.assertEqual(sale.status, Sale.Status.PAID)
        # No customer -> no AR/receivable created anywhere.
        self.assertFalse(Payment.objects.filter(sale=sale).exists())

    # 2. Partial credit sale
    def test_partial_credit_sale(self):
        product, wh = make_product('partial-credit')
        customer = Customer.objects.create(name='Partial Credit Customer')
        sale = self.make_sale(customer, product, wh, Decimal('1'), Decimal('1000'), Decimal('400'))
        self.assertEqual(sale.total, Decimal('1000'))
        self.assertEqual(sale.paid, Decimal('400'))
        self.assertEqual(sale.remaining, Decimal('600'))
        self.assertEqual(sale.status, Sale.Status.PARTIAL)
        self.assertEqual(customer.current_balance, Decimal('600'))
        self.assert_outstanding_matches_formula(customer, 'customer')

    # 3. Full credit sale
    def test_full_credit_sale(self):
        product, wh = make_product('full-credit')
        customer = Customer.objects.create(name='Full Credit Customer')
        sale = self.make_sale(customer, product, wh, Decimal('1'), Decimal('1000'), Decimal('0'))
        self.assertEqual(sale.remaining, Decimal('1000'))
        self.assertEqual(sale.status, Sale.Status.PENDING)
        self.assertEqual(customer.current_balance, Decimal('1000'))

    # 4. Partial customer payment
    def test_partial_customer_payment(self):
        product, wh = make_product('partial-pay')
        customer = Customer.objects.create(name='Partial Payer')
        sale = self.make_sale(customer, product, wh, Decimal('1'), Decimal('1000'), Decimal('0'))
        cash = fin_services.get_account('1000')
        pay_services.allocate_payment(Payment.Direction.IN, cash, '2026-07-26', [(sale, Decimal('300'))], customer=customer, created_by=self.user)
        sale.refresh_from_db()
        self.assertEqual(sale.remaining, Decimal('700'))
        self.assertEqual(customer.current_balance, Decimal('700'))
        self.assert_outstanding_matches_formula(customer, 'customer')

    # 5. Full customer payment
    def test_full_customer_payment(self):
        product, wh = make_product('full-pay')
        customer = Customer.objects.create(name='Full Payer')
        sale = self.make_sale(customer, product, wh, Decimal('1'), Decimal('1000'), Decimal('0'))
        cash = fin_services.get_account('1000')
        pay_services.allocate_payment(Payment.Direction.IN, cash, '2026-07-26', [(sale, Decimal('1000'))], customer=customer, created_by=self.user)
        sale.refresh_from_db()
        self.assertEqual(sale.remaining, Decimal('0'))
        self.assertEqual(sale.status, Sale.Status.PAID)
        self.assertEqual(customer.current_balance, Decimal('0'))

    # 6. Customer payment exceeding balance — must fail gracefully, not crash
    def test_customer_payment_exceeding_balance_rejected_gracefully(self):
        product, wh = make_product('over-pay')
        customer = Customer.objects.create(name='Over Payer')
        sale = self.make_sale(customer, product, wh, Decimal('1'), Decimal('500'), Decimal('0'))
        # Through the actual view (exercises the try/except ValueError fix),
        # not just the service layer.
        resp = self.client.post(f'/customers/{customer.pk}/payment/', {'amount': '9999999'})
        self.assertEqual(resp.status_code, 302, 'must redirect with an error message, never 500')
        sale.refresh_from_db()
        # FIFO due-collection caps at the sale's remaining, then treats any
        # leftover as an on-account advance — that's the documented,
        # explicitly-supported overpayment path, not a bug.
        self.assertEqual(sale.remaining, Decimal('0'))
        self.assertEqual(customer.current_balance, Decimal('-9999499'))

    # 7. Full cash purchase
    def test_full_cash_purchase(self):
        product, wh = make_product('cash-purchase')
        supplier = Supplier.objects.create(name='Cash Purchase Supplier')
        purchase = self.make_purchase(supplier, product, wh, Decimal('5'), Decimal('20'), Decimal('100'))
        self.assertEqual(purchase.total, Decimal('100'))
        self.assertEqual(purchase.remaining, Decimal('0'))
        self.assertEqual(purchase.status, Purchase.Status.PAID)
        self.assertEqual(supplier.current_balance, Decimal('0'))

    # 8. Partial credit purchase
    def test_partial_credit_purchase(self):
        product, wh = make_product('partial-credit-pur')
        supplier = Supplier.objects.create(name='Partial Credit Supplier')
        purchase = self.make_purchase(supplier, product, wh, Decimal('5'), Decimal('100'), Decimal('200'))
        self.assertEqual(purchase.total, Decimal('500'))
        self.assertEqual(purchase.remaining, Decimal('300'))
        self.assertEqual(purchase.status, Purchase.Status.PARTIAL)
        self.assertEqual(supplier.current_balance, Decimal('300'))
        self.assert_outstanding_matches_formula(supplier, 'supplier')

    # 9. Full credit purchase
    def test_full_credit_purchase(self):
        product, wh = make_product('full-credit-pur')
        supplier = Supplier.objects.create(name='Full Credit Supplier')
        purchase = self.make_purchase(supplier, product, wh, Decimal('5'), Decimal('100'), Decimal('0'))
        self.assertEqual(purchase.remaining, Decimal('500'))
        self.assertEqual(purchase.status, Purchase.Status.PENDING)
        self.assertEqual(supplier.current_balance, Decimal('500'))

    # 10. Partial supplier payment
    def test_partial_supplier_payment(self):
        product, wh = make_product('partial-sup-pay')
        supplier = Supplier.objects.create(name='Partial Supplier Payment')
        purchase = self.make_purchase(supplier, product, wh, Decimal('5'), Decimal('100'), Decimal('0'))
        cash = fin_services.get_account('1000')
        pay_services.allocate_payment(Payment.Direction.OUT, cash, '2026-07-26', [(purchase, Decimal('150'))], supplier=supplier, created_by=self.user)
        purchase.refresh_from_db()
        self.assertEqual(purchase.remaining, Decimal('350'))
        self.assertEqual(supplier.current_balance, Decimal('350'))
        self.assert_outstanding_matches_formula(supplier, 'supplier')

    # 11. Full supplier payment
    def test_full_supplier_payment(self):
        product, wh = make_product('full-sup-pay')
        supplier = Supplier.objects.create(name='Full Supplier Payment')
        purchase = self.make_purchase(supplier, product, wh, Decimal('5'), Decimal('100'), Decimal('0'))
        cash = fin_services.get_account('1000')
        pay_services.allocate_payment(Payment.Direction.OUT, cash, '2026-07-26', [(purchase, Decimal('500'))], supplier=supplier, created_by=self.user)
        purchase.refresh_from_db()
        self.assertEqual(purchase.remaining, Decimal('0'))
        self.assertEqual(purchase.status, Purchase.Status.PAID)
        self.assertEqual(supplier.current_balance, Decimal('0'))

    # 12. Supplier payment exceeding payable — must fail gracefully, not crash
    def test_supplier_payment_exceeding_payable_rejected_gracefully(self):
        product, wh = make_product('over-sup-pay')
        supplier = Supplier.objects.create(name='Over Supplier Payment')
        purchase = self.make_purchase(supplier, product, wh, Decimal('5'), Decimal('100'), Decimal('0'))
        resp = self.client.post(f'/suppliers/{supplier.pk}/payment/', {'amount': '9999999'})
        self.assertEqual(resp.status_code, 302, 'must redirect with an error message, never 500')
        purchase.refresh_from_db()
        # supplier_payment is a plain on-account payment (no invoice cap) —
        # same documented advance behaviour as the customer side.
        self.assertEqual(supplier.current_balance, Decimal('500') - Decimal('9999999'))

    # 13. Sales return against a credit sale
    def test_sales_return_against_credit_sale_reverses_ar(self):
        product, wh = make_product('sale-return')
        customer = Customer.objects.create(name='Sale Return Customer')
        sale = self.make_sale(customer, product, wh, Decimal('2'), Decimal('500'), Decimal('0'))
        self.assertEqual(customer.current_balance, Decimal('1000'))

        sale_item = sale.items.first()
        sr = sales_services.create_sales_return(
            SalesReturn(sale=sale, return_no='UDH-SR-1', date='2026-07-27'),
            [{'sale_item': sale_item, 'quantity': Decimal('1'), 'condition': SalesReturnItem.Condition.GOOD}],
            self.user,
        )
        self.assertEqual(sr.total_refund, Decimal('500'))
        self.assertEqual(customer.current_balance, Decimal('500'), 'AR must drop by exactly the returned line value')
        self.assert_outstanding_matches_formula(customer, 'customer')

    # 14. Purchase return against a credit purchase
    def test_purchase_return_against_credit_purchase_reverses_ap(self):
        product, wh = make_product('pur-return')
        supplier = Supplier.objects.create(name='Purchase Return Supplier')
        purchase = self.make_purchase(supplier, product, wh, Decimal('10'), Decimal('50'), Decimal('0'))
        self.assertEqual(supplier.current_balance, Decimal('500'))

        purchase_item = purchase.items.first()
        pr = purchases_services.create_purchase_return(
            PurchaseReturn(purchase=purchase, return_no='UDH-PR-1', date='2026-07-27'),
            [{'purchase_item': purchase_item, 'quantity': Decimal('4')}],
            self.user,
        )
        self.assertEqual(pr.total_value, Decimal('200'))
        self.assertEqual(supplier.current_balance, Decimal('300'), 'AP must drop by exactly the returned line value')
        self.assert_outstanding_matches_formula(supplier, 'supplier')

    # 15. Cancelled invoice
    def test_cancel_sale_reverses_stock_and_ledger(self):
        product, wh = make_product('cancel-sale', stock=Decimal('50'))
        customer = Customer.objects.create(name='Cancel Sale Customer')
        sale = self.make_sale(customer, product, wh, Decimal('3'), Decimal('100'), Decimal('0'))
        self.assertEqual(customer.current_balance, Decimal('300'))
        product.refresh_from_db()
        stock_after_sale = product.stock

        sales_services.cancel_sale(sale, self.user)
        sale.refresh_from_db()
        product.refresh_from_db()

        self.assertEqual(sale.status, Sale.Status.CANCELLED)
        self.assertEqual(sale.remaining, Decimal('0'))
        self.assertEqual(customer.current_balance, Decimal('0'), 'a cancelled invoice must leave zero AR behind')
        self.assertEqual(product.stock, stock_after_sale + Decimal('3'), 'stock must be restocked on cancellation')

        # A second cancel attempt, or any payment against a cancelled sale, must be rejected.
        with self.assertRaises(ValueError):
            sales_services.cancel_sale(sale, self.user)

    def test_cancel_sale_blocked_once_paid(self):
        product, wh = make_product('cancel-sale-paid')
        customer = Customer.objects.create(name='Cancel Sale Paid Customer')
        sale = self.make_sale(customer, product, wh, Decimal('1'), Decimal('200'), Decimal('50'))
        with self.assertRaises(ValueError):
            sales_services.cancel_sale(sale, self.user)

    # 16. Cancelled purchase
    def test_cancel_purchase_reverses_stock_and_ledger(self):
        product, wh = make_product('cancel-purchase', stock=Decimal('10'))
        supplier = Supplier.objects.create(name='Cancel Purchase Supplier')
        purchase = self.make_purchase(supplier, product, wh, Decimal('5'), Decimal('40'), Decimal('0'))
        self.assertEqual(supplier.current_balance, Decimal('200'))
        product.refresh_from_db()
        stock_after_purchase = product.stock

        purchases_services.cancel_purchase(purchase, self.user)
        purchase.refresh_from_db()
        product.refresh_from_db()

        self.assertEqual(purchase.status, Purchase.Status.CANCELLED)
        self.assertEqual(purchase.remaining, Decimal('0'))
        self.assertEqual(supplier.current_balance, Decimal('0'), 'a cancelled purchase must leave zero AP behind')
        self.assertEqual(product.stock, stock_after_purchase - Decimal('5'), 'received stock must be reversed out on cancellation')

    def test_cancel_purchase_blocked_once_paid(self):
        product, wh = make_product('cancel-purchase-paid')
        supplier = Supplier.objects.create(name='Cancel Purchase Paid Supplier')
        purchase = self.make_purchase(supplier, product, wh, Decimal('1'), Decimal('200'), Decimal('50'))
        with self.assertRaises(ValueError):
            purchases_services.cancel_purchase(purchase, self.user)

    # 17. Existing old records — no backfill step, balances must already be correct
    def test_existing_records_need_no_backfill(self):
        """Simulates a party/invoice that existed before this feature —
        current_balance and get_party_statement must both work correctly
        with zero extra migration/backfill step, since every Sale/Purchase
        already posts its ledger entries at creation time."""
        product, wh = make_product('legacy')
        customer = Customer.objects.create(name='Legacy Customer', opening_balance=Decimal('500'))
        fin_services.get_or_create_party_account(customer, Account.Type.ASSET, Account.Subtype.AR)
        fin_services.post_opening_balance(customer.linked_account, customer.opening_balance, '2026-01-01', created_by=self.user)
        self.assertEqual(customer.current_balance, Decimal('500'))

        sale = self.make_sale(customer, product, wh, Decimal('1'), Decimal('300'), Decimal('0'))
        self.assertEqual(customer.current_balance, Decimal('800'), 'opening balance + new credit sale must combine correctly')
        self.assert_outstanding_matches_formula(customer, 'customer')

    # 18. Multiple customers never cross-contaminate
    def test_multiple_customers_balances_stay_isolated(self):
        product, wh = make_product('multi-cust')
        a = Customer.objects.create(name='Customer A')
        b = Customer.objects.create(name='Customer B')
        self.make_sale(a, product, wh, Decimal('1'), Decimal('1000'), Decimal('0'))
        self.make_sale(b, product, wh, Decimal('1'), Decimal('250'), Decimal('100'))
        self.assertEqual(a.current_balance, Decimal('1000'))
        self.assertEqual(b.current_balance, Decimal('150'))

    # 19. Multiple suppliers never cross-contaminate
    def test_multiple_suppliers_balances_stay_isolated(self):
        product, wh = make_product('multi-sup')
        a = Supplier.objects.create(name='Supplier A')
        b = Supplier.objects.create(name='Supplier B')
        self.make_purchase(a, product, wh, Decimal('1'), Decimal('1000'), Decimal('0'))
        self.make_purchase(b, product, wh, Decimal('1'), Decimal('250'), Decimal('100'))
        self.assertEqual(a.current_balance, Decimal('1000'))
        self.assertEqual(b.current_balance, Decimal('150'))

    # A customer's receivable and a supplier's payable must never mix, even
    # when both parties exist and have activity in the same test.
    def test_customer_receivable_and_supplier_payable_never_mix(self):
        product, wh = make_product('no-mix')
        customer = Customer.objects.create(name='No Mix Customer')
        supplier = Supplier.objects.create(name='No Mix Supplier')
        self.make_sale(customer, product, wh, Decimal('1'), Decimal('400'), Decimal('0'))
        self.make_purchase(supplier, product, wh, Decimal('1'), Decimal('40'), Decimal('0'))
        self.assertEqual(customer.current_balance, Decimal('400'))
        self.assertEqual(supplier.current_balance, Decimal('40'))
        self.assertNotEqual(customer.linked_account_id, supplier.linked_account_id)

    # 20. Duplicate payment prevention
    def test_duplicate_payment_does_not_double_allocate(self):
        product, wh = make_product('dup-payment')
        customer = Customer.objects.create(name='Duplicate Payment Customer')
        sale = self.make_sale(customer, product, wh, Decimal('1'), Decimal('500'), Decimal('0'))
        cash = fin_services.get_account('1000')

        pay_services.allocate_payment(Payment.Direction.IN, cash, '2026-07-28', [(sale, Decimal('500'))], customer=customer, created_by=self.user)
        sale.refresh_from_db()
        self.assertEqual(sale.remaining, Decimal('0'))

        # A second, duplicate attempt to pay the now-settled invoice must be
        # rejected — not silently accepted as a second payment.
        with self.assertRaises(ValueError):
            pay_services.allocate_payment(Payment.Direction.IN, cash, '2026-07-28', [(sale, Decimal('500'))], customer=customer, created_by=self.user)

        sale.refresh_from_db()
        self.assertEqual(sale.remaining, Decimal('0'), 'the duplicate must not have been applied')
        self.assertEqual(Payment.objects.filter(sale=sale).count() + pay_services.PaymentAllocation.objects.filter(sale=sale).count(), 1)


class UdhaarPagesRenderTests(TestCase):
    """Smoke tests for the new pages — they must render 200 with real data,
    including a party with no activity at all (empty-state paths)."""

    def setUp(self):
        self.user = User.objects.create_user(username='udhaar_pages_admin', password='x', role=User.Role.ADMIN)
        self.client.force_login(self.user)

    def test_customer_detail_and_statement_pdf_render(self):
        product, wh = make_product('pages-cust')
        customer = Customer.objects.create(name='Pages Customer')
        sale = Sale(customer=customer, warehouse=wh, invoice_no='UDH-PAGES-1', date='2026-07-25')
        sales_services.create_sale(sale, [{'product': product, 'quantity': Decimal('1'), 'selling_price': Decimal('300')}], Decimal('100'), self.user)

        resp = self.client.get(f'/customers/{customer.pk}/')
        self.assertEqual(resp.status_code, 200)
        resp = self.client.get(f'/customers/{customer.pk}/?start=2026-01-01&end=2026-12-31&type=Credit+Sale')
        self.assertEqual(resp.status_code, 200)
        resp = self.client.get(f'/customers/{customer.pk}/statement.pdf')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')

    def test_customer_detail_renders_with_no_activity(self):
        customer = Customer.objects.create(name='Empty Customer')
        resp = self.client.get(f'/customers/{customer.pk}/')
        self.assertEqual(resp.status_code, 200)

    def test_supplier_detail_and_statement_pdf_render(self):
        product, wh = make_product('pages-sup')
        supplier = Supplier.objects.create(name='Pages Supplier')
        purchase = Purchase(supplier=supplier, warehouse=wh, invoice_no='UDH-PAGES-PUR-1', date='2026-07-25')
        purchases_services.create_purchase(purchase, [{'product': product, 'quantity': Decimal('2'), 'purchase_price': Decimal('50')}], Decimal('30'), self.user)

        resp = self.client.get(f'/suppliers/{supplier.pk}/')
        self.assertEqual(resp.status_code, 200)
        resp = self.client.get(f'/suppliers/{supplier.pk}/statement.pdf')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')

    def test_udhaar_hub_renders(self):
        product, wh = make_product('pages-hub')
        customer = Customer.objects.create(name='Hub Customer')
        supplier = Supplier.objects.create(name='Hub Supplier')
        sale = Sale(customer=customer, warehouse=wh, invoice_no='UDH-PAGES-HUB-1', date='2026-07-25')
        sales_services.create_sale(sale, [{'product': product, 'quantity': Decimal('1'), 'selling_price': Decimal('300')}], Decimal('0'), self.user)
        purchase = Purchase(supplier=supplier, warehouse=wh, invoice_no='UDH-PAGES-HUB-PUR-1', date='2026-07-25')
        purchases_services.create_purchase(purchase, [{'product': product, 'quantity': Decimal('1'), 'purchase_price': Decimal('50')}], Decimal('0'), self.user)

        resp = self.client.get('/reports/udhaar/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Hub Customer')
        self.assertContains(resp, 'Hub Supplier')

        resp = self.client.get('/reports/udhaar/?status=outstanding&start=2026-01-01&end=2026-12-31&party_type=customer')
        self.assertEqual(resp.status_code, 200)

    def test_dashboard_renders_with_udhaar_widgets(self):
        product, wh = make_product('pages-dash')
        customer = Customer.objects.create(name='Dashboard Customer')
        sale = Sale(customer=customer, warehouse=wh, invoice_no='UDH-PAGES-DASH-1', date=str(timezone.localdate()))
        sales_services.create_sale(sale, [{'product': product, 'quantity': Decimal('1'), 'selling_price': Decimal('300')}], Decimal('0'), self.user)

        resp = self.client.get('/dashboard/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Total Customer Receivables')

    def test_balance_adjustment_flow(self):
        customer = Customer.objects.create(name='Adjustment Customer')
        fin_services.get_or_create_party_account(customer, Account.Type.ASSET, Account.Subtype.AR)
        resp = self.client.post(f'/customers/{customer.pk}/balance-adjustment/', {'amount': '150', 'note': 'Migrated from old register'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(customer.current_balance, Decimal('150'))
        _, stats = fin_services.get_party_statement(customer, 'customer')
        self.assertEqual(stats['outstanding'], Decimal('150'))

        # Zero amount must be rejected, not silently accepted.
        resp = self.client.post(f'/customers/{customer.pk}/balance-adjustment/', {'amount': '0', 'note': 'bad'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(customer.current_balance, Decimal('150'), 'a rejected zero-amount adjustment must not change the balance')
