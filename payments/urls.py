from django.urls import path
from . import views

app_name = 'payments'

urlpatterns = [
    path('customers/<int:customer_id>/allocate/', views.customer_payment_allocate, name='customer_payment_allocate'),
    path('suppliers/<int:supplier_id>/allocate/', views.supplier_payment_allocate, name='supplier_payment_allocate'),
]
