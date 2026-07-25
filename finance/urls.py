from django.urls import path
from . import views

app_name = 'finance'

urlpatterns = [
    path('expenses/', views.expense_list, name='expense_list'),
    path('expenses/add/', views.expense_create, name='expense_create'),
    path('expenses/<int:pk>/delete/', views.expense_delete, name='expense_delete'),

    path('income/', views.income_list, name='income_list'),
    path('income/add/', views.income_create, name='income_create'),
    path('income/<int:pk>/delete/', views.income_delete, name='income_delete'),

    path('day-closing/', views.day_closing_list, name='day_closing_list'),
    path('day-closing/add/', views.day_closing_create, name='day_closing_create'),
    path('day-closing/<int:pk>/', views.day_closing_detail, name='day_closing_detail'),

    path('cash-registers/', views.cash_register_list, name='cash_register_list'),
    path('cash-registers/add/', views.cash_register_create, name='cash_register_create'),
    path('cash-registers/<int:pk>/', views.cash_register_detail, name='cash_register_detail'),
    path('cash-registers/<int:pk>/transaction/', views.cash_transaction_create, name='cash_transaction_create'),
]
