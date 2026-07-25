from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    path('', views.adjustment_list, name='adjustment_list'),
    path('add/', views.adjustment_create, name='adjustment_create'),
]
