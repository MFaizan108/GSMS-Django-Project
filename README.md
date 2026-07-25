# General Store Management System (GSMS)

A Django-based General Store / mini-ERP web app: products (with barcodes, multi
price levels, Excel import/export), multi-warehouse inventory with FIFO batch
tracking, suppliers & customers with running ledgers, purchase orders →
purchases → purchase returns, sales → sales returns, PDF invoices (with
shareable public links and email delivery), a real double-entry finance ledger
with cash registers and day-closing, notifications, a full audit trail, and
20+ reports — with role-based login (Admin / Manager / Cashier).

## 1. Tech stack

- Python / Django 5.x
- SQLite by default — PostgreSQL in production (set `DB_ENGINE=postgresql`, see `.env.example`)
- Bootstrap 5 + Bootstrap Icons (via CDN, no local build step/bundler needed)
- `python-barcode` (Code128 barcode label generation)
- `openpyxl` (product Excel import/export)
- `xhtml2pdf` (PDF invoice generation)

## 2. Requirements

- Python 3.10+ (3.12 recommended)
- pip
- PostgreSQL (optional — only needed if you set `DB_ENGINE=postgresql`; SQLite needs nothing extra)

## 3. Setup

```bash
cd gsms

# create & activate a virtual environment (recommended)
python -m venv venv
source venv/bin/activate        # on Windows: venv\Scripts\activate

# install dependencies
pip install -r requirements.txt

# copy the environment template and fill in real values
cp .env.example .env            # on Windows: copy .env.example .env

# create the database tables
python manage.py makemigrations
python manage.py migrate

# OPTION A: quick start with demo data + a ready-made admin login
python manage.py seed_demo
# -> creates username: admin / password: admin123  (role = Admin)
#    plus sample categories, brands, units, 4 demo products (one low-stock,
#    one already-expired), 1 supplier, 1 customer, and matching ledger/GL entries
#    (requires a default Warehouse to already exist — create one via /admin/ first)

# OPTION B: create your own admin user manually instead
python manage.py createsuperuser
# then log into /admin/ and set that user's "role" field to Admin

# run the development server
python manage.py runserver
```

Open **http://127.0.0.1:8000/** in your browser and log in.

Django admin panel (for direct DB editing / power users) is at **/admin/**.

### Environment variables (`.env`)

| Variable               | Purpose                                                        |
|-------------------------|-----------------------------------------------------------------|
| `DJANGO_SECRET_KEY`    | Django's secret key — generate a real random one for production |
| `DJANGO_DEBUG`         | `True`/`False` — must be `False` in production                  |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hostnames the site is served from                |
| `DB_ENGINE`            | Leave unset for SQLite (default); set to `postgresql` to use Postgres |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | PostgreSQL connection details (only used when `DB_ENGINE=postgresql`) |

## 4. Roles & permissions

Exactly three roles (`accounts.User.Role`):

| Role     | Access                                                              |
|----------|----------------------------------------------------------------------|
| Admin    | Everything, including Users and Store Settings                     |
| Manager  | Products, Suppliers, Purchases, Customers, Sales, Inventory, Reports, Finance |
| Cashier  | Sales entry, payments, viewing lists (no add/edit on masters)       |

A user can also be pinned to one `Warehouse` (branch) via `accounts.User.branch`;
leaving it blank gives access across all warehouses. Create additional users
from **Users** in the sidebar (Admin only), or via `/admin/`.

## 5. Apps / modules

- **accounts** — custom `User` model (role + branch fields), login/logout, role decorators
- **core** — shared base template, sidebar/topbar, notification-bell context processor, PDF renderer (`core/pdf.py`), email helper (`core/mail.py`)
- **dashboard** — today's sales/profit/purchases, cash in hand, low stock, expired, near-expiry, recent sales/purchases
- **products** — Category, Brand, Unit, Product (barcode, SKU, expiry, min stock, tax), ProductImage gallery, ProductBarcode (extra scan codes), ProductPrice (multi price-level pricing); printable barcode labels; Excel import/export
- **masters** — shared lookup tables: Tax and PriceLevel (actively used by products), plus PaymentMethod, Branch, ExpenseCategory, IncomeCategory, CustomerType, SupplierType (admin-editable now, not yet wired into other apps' workflows)
- **suppliers** — Supplier + auto-generated ledger (khata) + payment recording
- **customers** — Customer + auto-generated ledger (khata) + payment recording
- **inventory** — Warehouse, ProductBatch (FIFO/FEFO costing), BatchStock/WarehouseStock, StockTransfer between warehouses, StockAdjustment, and a full InventoryTransaction movement log
- **purchases** — optional PurchaseOrder draft workflow → Purchase (multi-item invoice, auto stock IN via batches, updates supplier ledger) → PurchaseReturn
- **sales** — Sale (multi-item invoice, FIFO batch allocation, auto stock OUT, per-item profit, updates customer ledger) → SalesReturn (restocks "good" condition items); PDF invoice, a public shareable invoice link, and email-invoice delivery
- **finance** — chart of Accounts, double-entry BusinessTransaction/LedgerEntry ledger, Payment (with multi-invoice allocation via the `payments` app), Expense, Income, CashRegister/CashTransaction, DayClosing (cash-drawer reconciliation)
- **payments** — PaymentAllocation: splits one Payment across multiple outstanding Sale/Purchase invoices
- **notifications** — in-app alerts (low stock, expired, near-expiry, customer due, supplier due) with a topbar bell + badge, refreshed on each dashboard/notifications-page visit
- **audit** — append-only AuditLog (who did what, when) written explicitly from accounts, inventory, finance, sales, and purchases actions (logins, price changes, stock adjustments/transfers, payments, returns, cancellations, day-closing, role changes)
- **reports** — 20 report views (see below), most with a date-range filter
- **settings_app** — Store name, owner, phone, address, logo, invoice footer, tax %, currency (single settings record used across the app, e.g. sidebar title, emailed invoices)

## 6. Reports

All under `/reports/`: overview, Sales, Purchases, Profit, Expenses, Stock,
Expiry, Low Stock, Top Selling, Least Selling, Customer Balance, Supplier
Balance, Payment Collection, Cash Flow, Stock Movement, Inventory Valuation,
ABC Analysis, Dead Stock, Account Reconciliation, and a combined Udhaar
(customer receivables + supplier payables) ledger hub. Reports render as HTML
only — no Excel/PDF export in this app (Excel export lives in **products**,
PDF export lives in the **sales**/**purchases** invoices).

## 7. Business logic notes (how the automation works)

- **Purchase saved** → for every line item, stock is received into a
  `ProductBatch` (FIFO cost basis) and `WarehouseStock`/`BatchStock` are
  updated; `product.purchase_price` is refreshed to the latest cost. The
  **supplier ledger** gets a debit entry for the invoice total, and a credit
  entry if any amount was paid immediately.
- **Sale saved** → stock availability is checked first (blocks the sale if
  insufficient); stock is deducted batch-by-batch (oldest/FIFO first) via
  `BatchAllocation`, capturing the true cost of goods sold for accurate
  profit. The **customer ledger** gets a debit entry for the invoice total
  (if a customer is attached) and a credit entry if any amount was paid
  immediately.
- **Sales/Purchase Return saved** → restocks "good" condition items back into
  their originating batch (via allocations) and reverses the relevant ledger
  entry; damaged/expired returns adjust stock without restocking sellable
  inventory.
- **Stock Adjustment / Stock Transfer saved** → directly changes
  `WarehouseStock`/`BatchStock` with a recorded reason, and logs an
  `InventoryTransaction` movement row plus an audit-log entry.
- **Payment recorded** → posted to the double-entry ledger (`finance.services.post_transaction`)
  and, when it covers more than one invoice, split via `payments.PaymentAllocation`.
- Ledgers are **never edited directly** — only generated from purchases,
  sales, returns, and payment actions; the double-entry ledger is
  append-only and posted only through `finance.services`.

## 8. What's defined but not yet fully wired up

- `masters.PaymentMethod`, `Branch`, `ExpenseCategory`, `IncomeCategory`,
  `CustomerType`, `SupplierType` — models and admin screens exist, but no
  other app references them yet (e.g. Expense/Income have no category FK
  yet; `inventory.Warehouse` is what's actually used for branches today).
- `products.ProductVariant` — model exists, explicitly reserved for future
  use; not connected to batches, stock, sales, or purchases yet.
- No dedicated Excel/PDF export inside the **reports** app itself.
- No Dockerfile/docker-compose, no LICENSE file, no CI config yet.

## 9. Tests

Every business app ships real tests (not stubs) — run the full suite with:

```bash
python manage.py test
```

Notable coverage: `finance/test_udhaar.py` (customer/supplier ledger
behavior), `payments/tests.py` (multi-invoice payment allocation),
`accounts/tests.py` (role and branch-restriction checks).
