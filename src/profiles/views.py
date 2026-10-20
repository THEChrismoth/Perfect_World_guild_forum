import logging

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.models import User
from django.db import transaction
from django.urls import reverse
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.contrib.auth.tokens import default_token_generator
from core import captcha
from core.mail import send_site_mail
from core.models import SiteSettings
from .forms import RegistrationForm, ProfileForm, UserForm

logger = logging.getLogger(__name__)


def send_verification_email(user, request, site_settings):
    # Генерация токена
    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))

    # Создание ссылки активации
    verification_url = request.build_absolute_uri(
        reverse('verify_email', kwargs={'uidb64': uid, 'token': token})
    )

    subject = f'Подтверждение регистрации — {site_settings.site_name}'
    message = (
        f'Здравствуйте, {user.username}!\n\n'
        f'Для завершения регистрации на сайте «{site_settings.site_name}» перейдите по ссылке:\n'
        f'{verification_url}\n\n'
        'Если вы не регистрировались, просто проигнорируйте это письмо.'
    )
    send_site_mail(subject, message, [user.email], site_settings)


def register(request):
    site_settings = SiteSettings.load()
    if request.method == 'POST':
        form = RegistrationForm(request.POST, site_settings=site_settings)
        if form.is_valid():
            if not site_settings.email_verification:
                # Подтверждение почты выключено — аккаунт активен сразу, входим автоматически
                user = form.save()
                login(request, user)
                messages.success(request, f'Добро пожаловать, {user.username}! Регистрация завершена.')
                return redirect('/')

            try:
                # Если письмо не ушло, аккаунт не создаётся: иначе он остался бы
                # неактивным, а повторить регистрацию с тем же именем было бы нельзя
                with transaction.atomic():
                    user = form.save(commit=False)
                    user.is_active = False  # Пользователь неактивен до подтверждения
                    user.save()
                    send_verification_email(user, request, site_settings)
            except Exception:
                logger.exception('Не удалось отправить письмо подтверждения регистрации')
                from notifications.utils import send_notification_to_admins
                send_notification_to_admins(
                    title='⚠️ Не отправляются письма регистрации',
                    message='Не удалось отправить письмо подтверждения регистрации. '
                            'Проверьте настройки почты: Настройки сайта → Почта (SMTP) → «Отправить тестовое письмо».',
                    notification_type='error',
                    link=reverse('admin:core_sitesettings_change', args=[site_settings.pk]),
                )
                form.add_error(None, 'Не удалось отправить письмо с подтверждением. '
                                     'Попробуйте позже — администраторы уже получили уведомление.')
            else:
                messages.success(request,
                                 'Регистрация почти завершена! Перейдите по ссылке из письма, '
                                 'которое мы отправили на вашу почту (проверьте и папку «Спам»).')
                return redirect('login')
    else:
        form = RegistrationForm(site_settings=site_settings)
    return render(request, 'registration/register.html', {
        'form': form,
        'captcha_active': site_settings.captcha_active,
        'captcha_site_key': site_settings.captcha_site_key,
        'captcha_script_url': captcha.SCRIPT_URL,
    })


def verify_email(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)

        if default_token_generator.check_token(user, token):
            user.is_active = True
            user.save()
            messages.success(request, 'Email подтверждён! Теперь вы можете войти.')
            return redirect('login')
        else:
            messages.error(request, 'Ссылка подтверждения недействительна или истекла.')
            return redirect('register')
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        messages.error(request, 'Ошибка подтверждения email.')
        return redirect('register')

@login_required
def profile_view(request, username):
    user = get_object_or_404(User, username=username)
    profile = user.profile
    is_owner = request.user == user
    
    # Проверяем, состоит ли пользователь в группе "Член гильдии"
    is_guild_member = user.groups.filter(name='Член гильдии').exists()

    context = {
        'profile_user': user,
        'profile': profile,
        'is_owner': is_owner,
        'is_guild_member': is_guild_member,
    }
    if is_owner:
        from teamspeak.views import card_context
        context.update(card_context(request, user))
    return render(request, 'profiles/profile_view.html', context)

@login_required
def profile_edit(request):
    if request.method == 'POST':
        user_form = UserForm(request.POST, instance=request.user)
        profile_form = ProfileForm(request.POST, request.FILES, instance=request.user.profile)
        
        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile = profile_form.save(commit=False)
            
            # Обработка очистки аватара
            if request.POST.get('avatar-clear') == 'on':
                if profile.avatar:
                    profile.avatar.delete(save=False)
                    profile.avatar = None
            
            profile.save()
            messages.success(request, 'Профиль успешно обновлен!')
            return redirect('profile_view', username=request.user.username)
        else:
            messages.error(request, 'Пожалуйста, исправьте ошибки в форме.')
    else:
        user_form = UserForm(instance=request.user)
        profile_form = ProfileForm(instance=request.user.profile)
    
    context = {
        'user_form': user_form,
        'profile_form': profile_form,
    }
    return render(request, 'profiles/profile_edit.html', context)
