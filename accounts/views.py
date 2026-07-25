from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from audit import services as audit_services
from audit.models import AuditLog
from .decorators import admin_required
from .models import User
from .forms import UserCreateForm, UserEditForm


def _client_ip(request):
    return request.META.get('REMOTE_ADDR')


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard:index')
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            audit_services.log_action(user, AuditLog.Action.LOGIN, 'accounts', user, ip_address=_client_ip(request))
            return redirect('dashboard:index')
        # No user object exists for a failed attempt, so there's nothing to
        # attach the log row to as `obj` — log_action requires one. A plain
        # AuditLog.objects.create() with object_type='User' and the attempted
        # username in new_data keeps the failed attempt on record regardless.
        AuditLog.objects.create(
            user=None, action=AuditLog.Action.FAILED_LOGIN, module='accounts',
            object_type='User', object_repr=username, new_data={'attempted_username': username},
            ip_address=_client_ip(request),
        )
        messages.error(request, 'Invalid username or password.')
    return render(request, 'accounts/login.html')


@login_required
def logout_view(request):
    audit_services.log_action(request.user, AuditLog.Action.LOGOUT, 'accounts', request.user, ip_address=_client_ip(request))
    logout(request)
    return redirect('accounts:login')


@admin_required
def user_list(request):
    users = User.objects.all().order_by('username')
    return render(request, 'accounts/user_list.html', {'users': users})


@admin_required
def user_create(request):
    if request.method == 'POST':
        form = UserCreateForm(request.POST, request.FILES)
        if form.is_valid():
            new_user = form.save()
            audit_services.log_action(
                request.user, AuditLog.Action.CREATE, 'accounts', new_user,
                new_data={'username': new_user.username, 'role': new_user.role},
            )
            messages.success(request, 'User created successfully.')
            return redirect('accounts:user_list')
    else:
        form = UserCreateForm()
    return render(request, 'accounts/user_form.html', {'form': form})


@admin_required
def user_edit(request, pk):
    user = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        old_role = user.role
        form = UserEditForm(request.POST, request.FILES, instance=user)
        if form.is_valid():
            updated_user = form.save()
            if updated_user.role != old_role:
                audit_services.log_action(
                    request.user, AuditLog.Action.ROLE_CHANGE, 'accounts', updated_user,
                    old_data={'role': old_role}, new_data={'role': updated_user.role},
                )
            else:
                audit_services.log_action(
                    request.user, AuditLog.Action.UPDATE, 'accounts', updated_user,
                    new_data={'username': updated_user.username},
                )
            messages.success(request, 'User updated successfully.')
            return redirect('accounts:user_list')
    else:
        form = UserEditForm(instance=user)
    return render(request, 'accounts/user_edit_form.html', {'form': form, 'edited_user': user})


@admin_required
def user_delete(request, pk):
    user = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        if user == request.user:
            messages.error(request, 'You cannot delete your own account.')
        else:
            audit_services.log_action(
                request.user, AuditLog.Action.DELETE, 'accounts', user,
                old_data={'username': user.username, 'role': user.role},
            )
            user.delete()
            messages.success(request, 'User deleted successfully.')
    return redirect('accounts:user_list')
