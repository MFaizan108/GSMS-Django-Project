from decimal import Decimal

from django.db import transaction
from finance.models import Payment

from finance import services as finance_services
from sales.models import Sale
from purchases.models import Purchase
from .models import PaymentAllocation


def allocate_payment(direction, account, date, invoice_allocations, customer=None, supplier=None, note='', created_by=None):
    """invoice_allocations: list of (Sale-or-Purchase, amount) — one physical
    payment covering multiple invoices. Creates a single finance.Payment (not
    tied to any one sale/purchase) plus one PaymentAllocation row per invoice,
    then recalculates each invoice's paid/remaining. Each line is checked
    against that invoice's live remaining balance (locked via select_for_update
    so two concurrent allocations against the same invoice can't both pass a
    stale check), and direction must match the invoice type — IN for Sale,
    OUT for Purchase — so a customer receipt can never be misfiled as a
    supplier payment or vice versa."""
    invoice_allocations = [(inv, amt) for inv, amt in invoice_allocations if amt and amt > 0]
    total = sum((amt for _, amt in invoice_allocations), Decimal('0'))
    if total <= 0:
        raise ValueError("Total allocation must be positive.")

    with transaction.atomic():
        for invoice, amount in invoice_allocations:
            if isinstance(invoice, Sale):
                if direction != Payment.Direction.IN:
                    raise ValueError(f"Sale #{invoice.invoice_no} can only take an incoming payment.")
                locked = Sale.objects.select_for_update().get(pk=invoice.pk)
            elif isinstance(invoice, Purchase):
                if direction != Payment.Direction.OUT:
                    raise ValueError(f"Purchase #{invoice.invoice_no} can only take an outgoing payment.")
                locked = Purchase.objects.select_for_update().get(pk=invoice.pk)
            else:
                raise ValueError(f"Unsupported invoice type: {invoice!r}")
            if amount > locked.remaining:
                raise ValueError(
                    f"Cannot allocate {amount} to {invoice}: only {locked.remaining} remaining."
                )

        payment = finance_services.record_payment(
            direction, total, account, date, customer=customer, supplier=supplier,
            note=note, created_by=created_by,
        )
        for invoice, amount in invoice_allocations:
            kwargs = {'sale': invoice} if isinstance(invoice, Sale) else {'purchase': invoice}
            PaymentAllocation.objects.create(payment=payment, amount=amount, **kwargs)
            invoice.recalculate()
    return payment
