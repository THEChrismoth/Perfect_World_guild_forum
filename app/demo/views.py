from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.http import Http404
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from .accounts import DEMO_ROLES


@require_POST
def demo_login(request, role):
    """Вход в демо-роль без пароля. Работает только при DEMO_MODE."""
    if not settings.DEMO_MODE or role not in DEMO_ROLES:
        raise Http404
    user = User.objects.filter(username=DEMO_ROLES[role]['username'], is_active=True).first()
    if user is None:
        messages.error(request, 'Демо-данные ещё не созданы: запустите python manage.py demo_seed')
        return redirect('/')
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    messages.success(request, f'Вы вошли как {DEMO_ROLES[role]["title"].lower()}.')
    return redirect('/')
