from django.urls import path
from . import views

app_name = 'customers'

urlpatterns = [
    path('', views.customer_list, name='customer_list'),
    path('add/', views.customer_create, name='customer_create'),
    path('<int:pk>/', views.customer_detail, name='customer_detail'),
    path('<int:pk>/edit/', views.customer_edit, name='customer_edit'),
    path('<int:pk>/delete/', views.customer_delete, name='customer_delete'),
    path('<int:pk>/payment/', views.customer_payment, name='customer_payment'),
    path('<int:pk>/give-payment/', views.customer_give_payment, name='customer_give_payment'),
    path('<int:pk>/record-payment/', views.customer_record_payment_api, name='customer_record_payment_api'),
    path('<int:pk>/statement.pdf', views.customer_statement_pdf, name='customer_statement_pdf'),
    path('<int:pk>/balance-adjustment/', views.customer_balance_adjustment, name='customer_balance_adjustment'),
]
