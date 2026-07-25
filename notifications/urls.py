from django.urls import path
from . import views

app_name = 'notifications'

urlpatterns = [
    path('', views.notification_list, name='notification_list'),
    path('<int:pk>/read/', views.notification_mark_read, name='notification_mark_read'),
    path('mark-all-read/', views.notification_mark_all_read, name='notification_mark_all_read'),
]
