from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from .models import Application, ApplicationVote
from .forms import ApplicationForm, VoteForm
from notifications.utils import send_notification


def check_guild_member(user):
    if user.is_superuser:
        return True
    return user.groups.filter(name='Член гильдии').exists()


@login_required
def application_form(request):
    if not hasattr(request.user, 'profile'):
        messages.error(request, 'У вас нет профиля.')
        return redirect('/')

    if not request.user.profile.player_class:
        messages.error(request, 'Сначала заполните профиль и выберите класс персонажа')
        return redirect('/profile/edit/')

    existing = Application.objects.filter(
        user=request.user,
        status__in=['pending', 'voting', 'approved']
    ).first()

    if existing:
        if existing.status == 'approved':
            messages.warning(request, 'Вы уже являетесь членом гильдии!')
        else:
            messages.warning(request, 'У вас уже есть активная заявка!')
        return redirect('reception:my_applications')

    if request.method == 'POST':
        form = ApplicationForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            app = form.save()
            messages.success(request, 'Заявка отправлена! Ожидайте проверки.')

            # Уведомление администраторам
            from notifications.utils import send_notification_to_admins
            send_notification_to_admins(
                title='📝 Новая заявка',
                message=f'Пользователь {request.user.username} подал новую заявку на вступление в гильдию.',
                notification_type='application',
                link=reverse('admin:reception_application_changelist')
            )
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

    return render(request, 'reception/my_applications.html', {
        'applications': applications,
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
                vote = ApplicationVote.objects.create(
                    application=application,
                    voter=request.user,
                    vote=form.cleaned_data['vote'],
                    comment=form.cleaned_data['comment']
                )
                messages.success(request, 'Ваш голос учтен!')

                # Уведомление автору заявки о голосе (если не воздержался)
                if vote.vote != 'abstain':
                    vote_text = 'ЗА' if vote.vote == 'for' else 'ПРОТИВ'
                    send_notification(
                        user=application.user,
                        title='🗳️ Новый голос в вашей заявке',
                        message=f'Пользователь {request.user.username} проголосовал {vote_text} по вашей заявке.',
                        notification_type='application',
                        link=reverse('reception:application_detail', args=[application.id])
                    )
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