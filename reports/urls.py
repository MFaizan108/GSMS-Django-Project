from django.urls import path
from . import views

app_name = 'reports'

urlpatterns = [
    path('', views.index, name='index'),
    path('sales/', views.sales_report, name='sales_report'),
    path('purchases/', views.purchase_report, name='purchase_report'),
    path('profit/', views.profit_report, name='profit_report'),
    path('expenses/', views.expense_report, name='expense_report'),
    path('stock/', views.stock_report, name='stock_report'),
    path('expiry/', views.expiry_report, name='expiry_report'),
    path('low-stock/', views.low_stock_report, name='low_stock_report'),
    path('top-selling/', views.top_selling_report, name='top_selling_report'),
    path('customer-balance/', views.customer_balance_report, name='customer_balance_report'),
    path('payment-collection/', views.payment_collection_report, name='payment_collection_report'),
    path('supplier-balance/', views.supplier_balance_report, name='supplier_balance_report'),
    path('cash-flow/', views.cash_flow_report, name='cash_flow_report'),
    path('least-selling/', views.least_selling_report, name='least_selling_report'),
    path('stock-movement/', views.stock_movement_report, name='stock_movement_report'),
    path('inventory-valuation/', views.inventory_valuation_report, name='inventory_valuation_report'),
    path('abc-analysis/', views.abc_analysis_report, name='abc_analysis_report'),
    path('dead-stock/', views.dead_stock_report, name='dead_stock_report'),
    path('account-reconciliation/', views.account_reconciliation_report, name='account_reconciliation_report'),
    path('udhaar/', views.udhaar_home, name='udhaar_home'),
]
