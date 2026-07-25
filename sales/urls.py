from django.urls import path
from . import views

app_name = 'sales'

urlpatterns = [
    path('', views.sale_list, name='sale_list'),
    path('add/', views.sale_create, name='sale_create'),
    path('api/products/search/', views.product_search_api, name='product_search_api'),
    path('api/customers/search/', views.customer_search_api, name='customer_search_api'),
    path('api/customers/quick-create/', views.customer_quick_create_api, name='customer_quick_create_api'),
    path('returns/', views.sales_return_list, name='sales_return_list'),
    path('returns/<int:pk>/', views.sales_return_detail, name='sales_return_detail'),
    path('<int:pk>/', views.sale_detail, name='sale_detail'),
    path('<int:pk>/invoice.pdf', views.sale_invoice_pdf, name='sale_invoice_pdf'),
    path('invoice/<uuid:token>/', views.sale_invoice_public_pdf, name='sale_invoice_public'),
    path('<int:pk>/email-invoice/', views.sale_email_invoice, name='sale_email_invoice'),
    path('<int:pk>/add-payment/', views.sale_add_payment, name='sale_add_payment'),
    path('<int:pk>/cancel/', views.sale_cancel, name='sale_cancel'),
    path('<int:sale_pk>/return/add/', views.sales_return_create, name='sales_return_create'),
]
