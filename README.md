# General Store Management System (GSMS)

A Django-based General Store / mini-ERP web app: products, categories/brands/units,
suppliers with ledger (khata), customers with ledger (khata), purchases (auto stock IN),
sales (auto stock OUT + profit), stock adjustments, expenses/income, dashboard, and
reports — with role-based login (Admin / Manager / Cashier).

This build covers the **core / Phase-1 blueprint**. Advanced Enterprise-v2 ideas
(FIFO batch-wise inventory, multi-warehouse, multi-branch, barcode scanning, audit
log UI, automatic backup) are **not** included yet — see "What's not included" below
for how the code is structured so these can be added later without a rewrite.

## 1. Requirements

- Python 3.10+ (3.12 recommended)
- pip

## 2. Setup (run these on your own machine / server — this was NOT run for you in this session)

```bash
cd gsms

# create & activate a virtual environment (recommended)
python -m venv venv
source venv/bin/activate        # on Windows: venv\Scripts\activate

# install dependencies
pip install -r requirements.txt

# create the database tables
python manage.py makemigrations
python manage.py migrate

# OPTION A: quick start with demo data + a ready-made admin login
python manage.py seed_demo
# -> creates username: admin / password: admin123  (role = Admin)
#    plus sample categories, brands, units, 4 demo products, 1 supplier, 1 customer

# OPTION B: create your own admin user manually instead
python manage.py createsuperuser
# then log into /admin/ and set that user's "role" field to Admin

# run the development server
python manage.py runserver
```

Open **http://127.0.0.1:8000/** in your browser and log in.

Django admin panel (for direct DB editing / power users) is at **/admin/**.

## 3. Roles & permissions

| Role     | Access                                                              |
|----------|----------------------------------------------------------------------|
| Admin    | Everything, including Users and Store Settings                     |
| Manager  | Products, Suppliers, Purchases, Customers, Sales, Inventory, Reports, Expenses/Income |
| Cashier  | Sales entry, Customer payments, viewing lists (no add/edit on masters) |

Create additional users from **Users** in the sidebar (Admin only), or via `/admin/`.

## 4. Modules included

- **accounts** — custom User model with role field, login/logout, role decorators
- **core** — shared base template, sidebar navigation, styling
- **dashboard** — today's sales/profit/purchases, cash in hand, low stock, expired,
  near-expiry, recent sales/purchases
- **products** — Category, Brand, Unit, Product (barcode/SKU fields, expiry, min stock)
- **suppliers** — Supplier + auto-generated ledger (khata) + payment recording
- **customers** — Customer + auto-generated ledger (khata) + payment recording
- **purchases** — Purchase + multi-item form → auto increases product stock, updates
  supplier ledger (debit for invoice total, credit for amount paid)
- **sales** — Sale + multi-item form → validates available stock, decreases stock,
  calculates per-item profit (selling price − purchase price), updates customer
  ledger for credit sales
- **inventory** — Stock Adjustment (damage / lost / returned / manual correction),
  increases or decreases product stock directly
- **finance** — Expenses and Income
- **reports** — Sales, Purchases, Profit, Expenses, Stock, Expiry, Low Stock,
  Top Selling Products, Customer Balance, Supplier Balance, Cash Flow (most with a
  date-range filter)
- **settings_app** — Store name, owner, phone, address, logo, invoice footer,
  tax %, currency (single settings record used across the app, e.g. in the sidebar title)

## 5. Business logic notes (how the automation works)

- **Purchase saved** → for every line item: `product.stock += quantity`,
  `product.purchase_price` is refreshed to the latest cost, and if an expiry date
  was entered it's copied onto the product. The **supplier ledger** gets a debit
  entry for the invoice total, and a credit entry if any amount was paid immediately.
- **Sale saved** → stock availability is checked first (blocks the sale if
  insufficient); for every line item `product.stock -= quantity`; profit per item
  is `(selling_price − purchase_price) × quantity`. The **customer ledger** gets a
  debit entry for the invoice total (if a customer is attached) and a credit entry
  if any amount was paid immediately.
- **Stock Adjustment saved** → directly increases or decreases `product.stock`,
  recorded with a reason (damage/lost/returned/manual correction).
- Ledgers are **never edited directly** — only generated from purchases, sales, and
  payment actions, matching the "ledger should not be hand-edited" principle from
  your blueprint.

## 6. What's not included yet (roadmap / easy to add later)

These were in the "Enterprise v2" blueprint but are out of scope for this first
build, since each is realistically its own mini-project:

- FIFO batch-wise inventory (currently: simple single running stock number per product)
- Multi-warehouse / multi-branch / multi-cash-counter support
- Purchase Return / Sales Return workflows
- Barcode generation, printing, and scanner input
- SMS/WhatsApp/Email invoice sharing
- Dashboard charts (Chart.js can be dropped into the dashboard template easily)
- Excel import/export
- Full Audit Log UI (Django admin's built-in history covers some of this already)
- Scheduled automatic database backup (manual export: `python manage.py dumpdata > backup.json`)
- Multi-payment-method-per-invoice (cash + bank + JazzCash split on one invoice)

The apps are already separated the way your blueprint asked (`purchases`, `sales`,
`inventory`, etc.), so each of the above can be added as new fields/models inside
its matching app without restructuring the project.

## 7. Important — this was not run/tested in a live server

This code was written directly (not scaffolded and executed) because the sandbox
that built it has no internet access to install Django. Please run the setup steps
above yourself. If you hit any errors when running `migrate` or `runserver`, send
me the exact error message and I'll fix it.
