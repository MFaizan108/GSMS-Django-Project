from django.urls import path
from . import views

app_name = 'settings_app'

urlpatterns = [
    path('', views.store_settings_view, name='store_settings'),
]
