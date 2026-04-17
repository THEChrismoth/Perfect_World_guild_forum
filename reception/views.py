from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from .models import Application, ApplicationVote, ApplicationNotification
from .forms import ApplicationForm, VoteForm

def check_guild_member(user):
    if user.is_superuser:
        return True
    return user.groups.filter(name='Член гильдии').exists()


@login_required
def application_form(request):
    # Проверка - член гильдии не может подать заявку
    if check_guild_member(request.user):
        messages.error(request, 'Вы уже являетесь членом гильдии и не можете подать заявку.')
        return redirect('/')
    
    if not hasattr(request.user, 'profile'):
        messages.error(request, 'У вас нет профиля.')
        return redirect('/')
    
    if not request.user.profile.player_class:
        messages.error(request, 'Сначала заполните профиль и выберите класс персонажа')
        return redirect('/profile/edit/')
    
    # Проверяем активные заявки (включая approved)
    existing = Application.objects.filter(
        user=request.user,
        status__in=['pending', 'voting', 'approved']
    ).first()
    
    if existing:
        if existing.status == 'approved':
            messages.warning(request, 'Вы уже являетесь членом гильдии! Ваша заявка одобрена.')
        else:
            messages.warning(request, 'У вас уже есть активная заявка!')
        return redirect('reception:my_applications')
    
    if request.method == 'POST':
        form = ApplicationForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            app = form.save()
            messages.success(request, 'Заявка отправлена! Ожидайте проверки.')
            return redirect('reception:application_success')
    else:
        form = ApplicationForm(user=request.user)
        if request.user.profile.age():
            form.fields['age'].initial = request.user.profile.age()
    
    return render(request, 'reception/application_form.html', {'form': form, 'profile': request.user.profile})


def application_success(request):
    return render(request, 'reception/application_success.html')


@login_required
def application_list(request):
    if not check_guild_member(request.user):
        raise PermissionDenied("Только члены гильдии могут просматривать заявки")
    
    applications = Application.objects.filter(status='voting').order_by('-approved_at')
    
    return render(request, 'reception/application_list.html', {
        'applications': applications,
        'is_guild_member': True,
    })


@login_required
def my_applications(request):
    applications = Application.objects.filter(user=request.user).order_by('-created_at')
    notifications = ApplicationNotification.objects.filter(user=request.user, is_read=False)
    
    # Помечаем уведомления как прочитанные
    notifications.update(is_read=True)
    
    return render(request, 'reception/my_applications.html', {
        'applications': applications,
        'notifications': notifications,
    })


@login_required
def application_detail(request, id):
    application = get_object_or_404(Application, id=id)
    
    is_guild_member = check_guild_member(request.user)
    is_admin = request.user.is_superuser or request.user.is_staff
    is_owner = request.user == application.user
    
    if not (is_owner or is_admin or (is_guild_member and application.status == 'voting')):
        raise PermissionDenied("Нет доступа к этой заявке")
    
    if request.method == 'POST' and application.status == 'voting' and is_guild_member and not is_owner:
        form = VoteForm(request.POST)
        if form.is_valid():
            if not application.has_voted(request.user):
                ApplicationVote.objects.create(
                    application=application,
                    voter=request.user,
                    vote=form.cleaned_data['vote'],
                    comment=form.cleaned_data['comment']
                )
                messages.success(request, 'Ваш голос учтен!')
        return redirect('reception:application_detail', id=application.id)
    else:
        form = VoteForm()
    
    profile = application.user.profile
    character_stats = {
        'hp': profile.hp, 'mp': profile.mp, 'pa': profile.pa, 'fa': profile.fa,
        'ma': profile.ma, 'pz': profile.pz, 'bd': profile.bd, 'bu': profile.bu,
        'physical_defense': profile.physical_defense, 'magic_defense': profile.magic_defense,
        'physical_pierce': profile.physical_pierce, 'magic_pierce': profile.magic_pierce,
        'crit_damage': profile.crit_damage, 'crit_chance': profile.crit_chance,
        'accuracy': profile.accuracy, 'dodge': profile.dodge,
    }
    
    vote_stats = application.get_vote_stats()
    user_voted = application.has_voted(request.user) if request.user.is_authenticated else False
    
    comments = []
    if is_guild_member or is_admin:
        comments = application.votes.exclude(comment='').order_by('-created_at')
    
    return render(request, 'reception/application_detail.html', {
        'application': application,
        'form': form,
        'vote_stats': vote_stats,
        'user_voted': user_voted,
        'is_guild_member': is_guild_member,
        'is_admin': is_admin,
        'is_owner': is_owner,
        'character_stats': character_stats,
        'comments': comments,
    })


@login_required
def mark_notification_read(request, notification_id):
    """Пометить уведомление как прочитанное"""
    notification = get_object_or_404(ApplicationNotification, id=notification_id, user=request.user)
    notification.is_read = True
    notification.save()
    return redirect('reception:my_applications')


@login_required
def mark_all_notifications_read(request):
    """Пометить все уведомления как прочитанные"""
    ApplicationNotification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return redirect('reception:my_applications')
