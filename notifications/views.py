from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from .models import Notification
from . import services


@login_required
def notification_list(request):
    services.refresh_notifications()
    notifications = Notification.objects.all()[:200]
    return render(request, 'notifications/notification_list.html', {'notifications': notifications})


@login_required
@require_POST
def notification_mark_read(request, pk):
    get_object_or_404(Notification, pk=pk)
    Notification.objects.filter(pk=pk).update(is_read=True)
    return redirect(request.POST.get('next') or 'notifications:notification_list')


@login_required
@require_POST
def notification_mark_all_read(request):
    Notification.objects.filter(is_read=False).update(is_read=True)
    return redirect(request.POST.get('next') or 'notifications:notification_list')
