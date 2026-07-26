from django.urls import path
from . import views

app_name = 'purchases'

urlpatterns = [
    path('', views.purchase_list, name='purchase_list'),
    path('add/', views.purchase_create, name='purchase_create'),
    path('products/search/', views.purchase_product_search_api, name='purchase_product_search_api'),
    path('returns/', views.purchase_return_list, name='purchase_return_list'),
    path('returns/<int:pk>/', views.purchase_return_detail, name='purchase_return_detail'),
    path('orders/', views.purchase_order_list, name='purchase_order_list'),
    path('orders/add/', views.purchase_order_create, name='purchase_order_create'),
    path('orders/<int:pk>/', views.purchase_order_detail, name='purchase_order_detail'),
    path('<int:pk>/', views.purchase_detail, name='purchase_detail'),
    path('<int:pk>/invoice.pdf', views.purchase_invoice_pdf, name='purchase_invoice_pdf'),
    path('<int:pk>/add-payment/', views.purchase_add_payment, name='purchase_add_payment'),
    path('<int:pk>/cancel/', views.purchase_cancel, name='purchase_cancel'),
    path('<int:purchase_pk>/return/add/', views.purchase_return_create, name='purchase_return_create'),
]
