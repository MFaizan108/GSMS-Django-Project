from django.urls import path
from . import views

app_name = 'products'

urlpatterns = [
    path('categories/', views.category_list, name='category_list'),
    path('categories/add/', views.category_create, name='category_create'),
    path('categories/<int:pk>/edit/', views.category_edit, name='category_edit'),
    path('categories/<int:pk>/delete/', views.category_delete, name='category_delete'),

    path('brands/', views.brand_list, name='brand_list'),
    path('brands/add/', views.brand_create, name='brand_create'),
    path('brands/<int:pk>/delete/', views.brand_delete, name='brand_delete'),

    path('units/', views.unit_list, name='unit_list'),
    path('units/add/', views.unit_create, name='unit_create'),
    path('units/<int:pk>/delete/', views.unit_delete, name='unit_delete'),

    path('', views.product_list, name='product_list'),
    path('add/', views.product_create, name='product_create'),
    path('<int:pk>/', views.product_detail, name='product_detail'),
    path('<int:pk>/edit/', views.product_edit, name='product_edit'),
    path('<int:pk>/delete/', views.product_delete, name='product_delete'),
    path('<int:pk>/barcode/', views.product_barcode_label, name='product_barcode_label'),
    path('export/excel/', views.product_export_excel, name='product_export_excel'),
    path('import/excel/', views.product_import_excel, name='product_import_excel'),
]
