import logging

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login
from django.contrib.auth.decorators import login_not_required, login_required
from django.contrib import messages
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db import transaction
from django.urls import reverse
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.views.decorators.http import require_POST
from django.contrib.auth.tokens import default_token_generator
from core import captcha
from core.mail import send_site_mail
from core.models import SiteSettings
from .forms import GearSetForm, RegistrationForm, ProfileForm, UserForm

logger = logging.getLogger(__name__)


def send_verification_email(user, request, site_settings):
    # Генерация токена.
    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))

    # Создание ссылки активации.
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


@login_not_required
def register(request):
    if request.user.is_authenticated:
        return redirect('/')
    site_settings = SiteSettings.load()
    if request.method == 'POST':
        form = RegistrationForm(request.POST, site_settings=site_settings)
        if form.is_valid():
            if not site_settings.email_verification:
                # Подтверждение почты выключено — аккаунт активен сразу, входим автоматически.
                user = form.save()
                login(request, user)
                messages.success(request, f'Добро пожаловать, {user.username}! Регистрация завершена.')
                return redirect('/')

            try:
                # Если письмо не ушло, аккаунт не создаётся: иначе он остался бы
                # неактивным, а повторить регистрацию с тем же именем было бы нельзя.
                with transaction.atomic():
                    user = form.save(commit=False)
                    user.is_active = False  # Пользователь неактивен до подтверждения
                    user.save()
                    form.save_profile(user)
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


@login_not_required
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
@require_POST
def set_accent(request):
    """Цвет оформления из меню профиля в верхней панели. Та же логика, что и в админ-панели."""
    from core.accents import handle_accent_post

    return handle_accent_post(request, '/')


@login_required
def profile_view(request, username):
    user = get_object_or_404(User, username=username)
    profile = user.profile
    is_owner = request.user == user
    
    # Проверяем, состоит ли пользователь в группе "Член гильдии".
    is_guild_member = user.groups.filter(name='Член гильдии').exists()

    context = {
        'profile_user': user,
        'profile': profile,
        'is_owner': is_owner,
        'is_guild_member': is_guild_member,
        'gear_sets': profile.gear_sets(),
    }
    # Очки и их история открыты всем: в гильдии всё прозрачно.
    context.update(_points_context(request, profile))
    if is_owner:
        from teamspeak.views import card_context
        context.update(card_context(request, user))
    return render(request, 'profiles/profile_view.html', context)


# Фильтр «Движения моих очков»: подпись и типы операций.
POINTS_FILTERS = {
    'all': ('Все', None),
    'credit': ('Начисления', ['credit']),
    'debit': ('Списания', ['debit']),
    'freeze': ('Заморозка на аукционе', ['freeze', 'unfreeze']),
}
POINTS_PER_PAGE = (10, 20, 50)


def _points_context(request, profile):
    """Очки активности игрока и история операций с фильтром и страницами."""
    from auction.models import PointsTransaction

    available = profile.get_available_points()
    kind = request.GET.get('points') if request.GET.get('points') in POINTS_FILTERS else 'all'
    per_page = (int(request.GET['per_page']) if request.GET.get('per_page') in map(str, POINTS_PER_PAGE)
                else POINTS_PER_PAGE[0])
    history = PointsTransaction.objects.filter(user=profile.user)
    if POINTS_FILTERS[kind][1]:
        history = history.filter(transaction_type__in=POINTS_FILTERS[kind][1])

    params = request.GET.copy()
    params.pop('page', None)
    return {
        'points': {'available': available, 'frozen': profile.activity_points - available,
                   'balance': profile.activity_points},
        'points_page': Paginator(history, per_page).get_page(request.GET.get('page')),
        'points_filters': [(key, label) for key, (label, _) in POINTS_FILTERS.items()],
        'points_filter': kind,
        'points_per_page': per_page,
        'points_per_page_choices': POINTS_PER_PAGE,
        'points_query': params.urlencode(),
    }

@login_required
def profile_edit(request):
    profile = request.user.profile
    data = request.POST if request.method == 'POST' else None
    user_form = UserForm(data, instance=request.user)
    profile_form = ProfileForm(data, request.FILES or None, instance=profile)
    # Два сета брони — две формы с приставками pa- и pz-, чтобы поля не путались.
    selected_class = request.POST.get('player_class', profile.player_class) if data is not None else profile.player_class
    set_forms = [GearSetForm(data, instance=gear, prefix=gear.kind, player_class=selected_class)
                 for gear in profile.gear_sets()]
    set_forms.sort(key=lambda form: form.instance.kind)

    if request.method == 'POST':
        if all(form.is_valid() for form in [user_form, profile_form, *set_forms]):
            user_form.save()
            profile = profile_form.save(commit=False)

            # Обработка очистки аватара.
            if request.POST.get('avatar-clear') == 'on':
                if profile.avatar:
                    profile.avatar.delete(save=False)
                    profile.avatar = None

            profile.save()
            for form in set_forms:
                form.save()
            messages.success(request, 'Профиль успешно обновлен!')
            return redirect('profile_view', username=request.user.username)
        messages.error(request, 'Пожалуйста, исправьте ошибки в форме.')

    context = {
        'user_form': user_form,
        'profile_form': profile_form,
        'sets': [{'kind': form.instance.kind, 'label': form.instance.get_kind_display(), 'form': form,
                  'groups': form.stat_groups()} for form in set_forms],
    }
    return render(request, 'profiles/profile_edit.html', context)
