from django.urls import path
from . import views

app_name = 'suppliers'

urlpatterns = [
    path('', views.supplier_list, name='supplier_list'),
    path('add/', views.supplier_create, name='supplier_create'),
    path('<int:pk>/', views.supplier_detail, name='supplier_detail'),
    path('<int:pk>/edit/', views.supplier_edit, name='supplier_edit'),
    path('<int:pk>/delete/', views.supplier_delete, name='supplier_delete'),
    path('<int:pk>/payment/', views.supplier_payment, name='supplier_payment'),
    path('<int:pk>/receive-refund/', views.supplier_receive_refund, name='supplier_receive_refund'),
    path('<int:pk>/statement.pdf', views.supplier_statement_pdf, name='supplier_statement_pdf'),
    path('<int:pk>/balance-adjustment/', views.supplier_balance_adjustment, name='supplier_balance_adjustment'),
]
