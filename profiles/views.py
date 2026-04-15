from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.urls import reverse
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.contrib.auth.tokens import default_token_generator
from django.conf import settings
from .forms import RegistrationForm, ProfileForm, UserForm

def send_verification_email(user, request):
    # Генерация токена
    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))

    # Создание ссылки активации
    verification_url = request.build_absolute_uri(
        reverse('verify_email', kwargs={'uidb64': uid, 'token': token})
    )

    print("\n" + "🔗" * 35)
    print("ССЫЛКА ДЛЯ ПОДТВЕРЖДЕНИЯ РЕГИСТРАЦИИ:")
    print(verification_url)
    print("🔗" * 35 + "\n")

    # Отправка письма
    subject = 'Подтверждение регистрации'
    message = f'''
    Здравствуйте, {user.username}!

    Для завершения регистрации перейдите по ссылке:
    {verification_url}

    Ссылка действительна в течение 24 часов.
    '''

    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [user.email])


def register(request):
    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = False  # Пользователь неактивен до подтверждения
            user.save()

            # Отправка письма с подтверждением
            send_verification_email(user, request)

            messages.success(request,
                             'Регистрация успешна! На вашу почту отправлено письмо с подтверждением.')
            return redirect('login')
    else:
        form = RegistrationForm()
    return render(request, 'profiles/register.html', {'form': form})


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
        user = None
        messages.error(request, 'Ошибка подтверждения email.')
        return redirect('register')

@login_required
def profile_view(request, username):
    user = get_object_or_404(User, username=username)
    profile = user.profile
    is_owner = request.user == user
    
    context = {
        'profile_user': user,
        'profile': profile,
        'is_owner': is_owner,
    }
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


