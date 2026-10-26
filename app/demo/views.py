from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.http import Http404
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from .accounts import DEMO_ROLES
from .guests import create_guest, find_guest, read_guests, remember_guest
from .limits import make_room, take_ip_slot


@require_POST
def demo_login(request, role):
    """Вход в демо-роль без пароля: в личный аккаунт этого браузера или в новый. Только при DEMO_MODE."""
    if not settings.DEMO_MODE or role not in DEMO_ROLES:
        raise Http404
    user = find_guest(role, read_guests(request).get(role))
    if user is None:
        if not take_ip_slot(request):
            messages.error(request, 'С вашего адреса создано слишком много демо-аккаунтов. Попробуйте через час.')
            return redirect('/')
        if not make_room():
            messages.error(request, 'Демо сейчас переполнено посетителями. Попробуйте через полчаса.')
            return redirect('/')
        user = create_guest(role)
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    messages.success(request, f'Вы вошли как {DEMO_ROLES[role]["title"].lower()} {user.username}.')
    response = redirect('/')
    remember_guest(request, response, role, user)
    return response
