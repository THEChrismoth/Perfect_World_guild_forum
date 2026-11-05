from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.urls import reverse
from django.views.decorators.http import require_POST
from .models import Application, ApplicationVote, ApplicationComment, vote_stats
from .forms import ApplicationForm
from .services import discussion_items
from notifications.utils import send_notification
from core.roles import is_guild_member as check_guild_member

# Вкладки списка заявок: что видно и какие статусы входят.
TABS = {
    'open': ('Открытые', ['voting']),
    'approved': ('Принятые', ['approved']),
    'rejected': ('Отклонённые', ['rejected']),
    'all': ('Все', ['voting', 'approved', 'rejected']),
}
SORTS = {'new': ('Сначала новые', '-created_at'), 'old': ('Сначала старые', 'created_at')}
PER_PAGE = (10, 20, 50)


@login_required
def application_form(request):
    # Члены гильдии заявки не подают, а голосуют по чужим.
    if check_guild_member(request.user):
        messages.info(request, 'Вы уже в гильдии — здесь можно голосовать по заявкам кандидатов.')
        return redirect('reception:application_list')

    if not hasattr(request.user, 'profile'):
        messages.error(request, 'У вас нет профиля.')
        return redirect('/')

    if not request.user.profile.player_class:
        messages.error(request, 'Перед подачей заявки заполните профиль: выберите класс персонажа и укажите характеристики. '
                                'Личные данные и характеристики попадут в заявку автоматически.')
        return redirect('profile_edit')

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

            # Уведомление администраторам и модераторам, которые рассматривают заявки.
            from notifications.utils import send_notification_to_admins
            send_notification_to_admins(
                title='📝 Новая заявка',
                message=f'Пользователь {request.user.username} подал новую заявку на вступление в гильдию.',
                notification_type='application',
                link=reverse('admin:reception_application_change', args=[app.id]),
                perm='reception.change_application',
            )
            return redirect('reception:application_success')
    else:
        form = ApplicationForm(user=request.user)

    return render(request, 'reception/application_form.html', {'form': form, 'profile': request.user.profile})


def application_success(request):
    return render(request, 'reception/application_success.html')


def _with_counts(applications):
    """Счётчики голосов и комментариев одним запросом вместе с заявками."""
    return applications.select_related('user__profile').annotate(
        votes_for=Count('votes', filter=Q(votes__vote='for'), distinct=True),
        votes_against=Count('votes', filter=Q(votes__vote='against'), distinct=True),
        votes_abstain=Count('votes', filter=Q(votes__vote='abstain'), distinct=True),
        comments_num=Count('comments', distinct=True),
        votes_with_text=Count('votes', filter=~Q(votes__comment=''), distinct=True),
    )


def _add_stats(applications):
    """Проценты в app.stats и число записей в обсуждении — для карточек списка."""
    for app in applications:
        app.stats = vote_stats(app.votes_for, app.votes_against, app.votes_abstain)
        app.discussion_count = app.comments_num + app.votes_with_text
    return applications


@login_required
def application_list(request):
    if not check_guild_member(request.user):
        raise PermissionDenied("Только члены гильдии могут просматривать заявки")

    tab = request.GET.get('tab') if request.GET.get('tab') in TABS else 'open'
    sort = request.GET.get('sort') if request.GET.get('sort') in SORTS else 'new'
    per_page = int(request.GET['per_page']) if request.GET.get('per_page') in map(str, PER_PAGE) else PER_PAGE[0]
    query = request.GET.get('q', '').strip()

    # Члены гильдии видят только заявки, дошедшие до голосования: отклонённые на проверке никто не обсуждал.
    applications = Application.objects.filter(status__in=TABS[tab][1], approved_at__isnull=False)
    if query:
        applications = applications.filter(
            Q(user__username__icontains=query) | Q(user__email__icontains=query) | Q(player_class__icontains=query) | Q(previous_nicknames__icontains=query)
            | Q(other_guilds__icontains=query) | Q(development_plans__icontains=query)
            | Q(guarantors__icontains=query)
        )
    applications = _with_counts(applications).order_by(SORTS[sort][1], '-id')

    page = Paginator(applications, per_page).get_page(request.GET.get('page'))
    page.object_list = _add_stats(list(page.object_list))

    # Ссылки вкладок и страниц сохраняют остальные параметры.
    params = request.GET.copy()
    params.pop('page', None)
    tab_params = params.copy()
    tab_params.pop('tab', None)

    return render(request, 'reception/application_list.html', {
        'page': page,
        'tabs': [(key, label) for key, (label, _) in TABS.items()],
        'tab': tab,
        'sorts': [(key, label) for key, (label, _) in SORTS.items()],
        'sort': sort,
        'per_page_choices': PER_PAGE,
        'per_page': per_page,
        'query': query,
        'page_query': params.urlencode(),
        'tab_query': tab_params.urlencode(),
    })


@login_required
def my_applications(request):
    applications = _add_stats(list(_with_counts(Application.objects.filter(user=request.user)).order_by('-created_at')))

    return render(request, 'reception/my_applications.html', {
        'applications': applications,
        'has_active': any(app.status in ('pending', 'voting', 'approved') for app in applications),
    })


def _access(request, application):
    """Кто что может в заявке: смотреть, видеть обсуждение, голосовать, комментировать."""
    user = request.user
    is_member = check_guild_member(user)
    is_admin = user.is_superuser or user.is_staff
    is_owner = user == application.user
    in_history = application.approved_at is not None and application.status in ('voting', 'approved', 'rejected')
    can_discuss = (is_member or is_admin) and not is_owner and (is_admin or in_history)
    if not (is_owner or can_discuss):
        raise PermissionDenied("Нет доступа к этой заявке")
    is_voting = application.status == 'voting'
    return {
        'is_owner': is_owner,
        'can_discuss': can_discuss,
        'can_vote': is_voting and is_member and not is_owner,
        'can_comment': is_voting and can_discuss,
    }


def _render_detail(request, application):
    access = _access(request, application)
    my_vote = application.votes.filter(voter=request.user).first()
    context = {
        'application': application,
        'profile': application.user.profile,
        'stats': application.get_vote_stats(),
        'my_vote': my_vote,
        # На сайте в ленте только тексты: комментарии и комментарии к голосам, кто как голосовал — в админ-панели.
        'items': [item for item in discussion_items(application) if item['text']] if access['can_discuss'] else [],
        **access,
    }
    # Во всплывающем окне — только содержимое, без каркаса сайта.
    template = 'reception/includes/discussion.html' if request.GET.get('modal') else 'reception/application_detail.html'
    return render(request, template, context)


@login_required
def application_detail(request, id):
    application = get_object_or_404(Application.objects.select_related('user__profile'), id=id)
    return _render_detail(request, application)


def _after_post(request, application):
    # Из окна обсуждения форма отправляется фоном — возвращаем обновлённое содержимое окна.
    if request.headers.get('X-Requested-With') == 'fetch':
        request.GET = request.GET.copy()
        request.GET['modal'] = '1'
        return _render_detail(request, application)
    return redirect('reception:application_detail', id=application.id)


@login_required
@require_POST
def application_vote(request, id):
    application = get_object_or_404(Application, id=id)
    vote = request.POST.get('vote')
    if not _access(request, application)['can_vote'] or vote not in dict(ApplicationVote.VOTE_CHOICES):
        raise PermissionDenied("Голосовать по этой заявке нельзя")

    _, created = ApplicationVote.objects.get_or_create(application=application, voter=request.user,
                                                       defaults={'vote': vote,
                                                                 'comment': request.POST.get('comment', '').strip()[:2000]})
    if created:
        messages.success(request, 'Ваш голос учтён!')
        # Уведомление автору заявки о голосе (если не воздержался).
        if vote != 'abstain':
            send_notification(
                user=application.user,
                title='🗳️ Новый голос в вашей заявке',
                message=f'Пользователь {request.user.username} проголосовал {"ЗА" if vote == "for" else "ПРОТИВ"} '
                        f'по вашей заявке.',
                notification_type='application',
                link=reverse('reception:application_detail', args=[application.id])
            )
    return _after_post(request, application)


@login_required
@require_POST
def application_comment(request, id):
    application = get_object_or_404(Application, id=id)
    if not _access(request, application)['can_comment']:
        raise PermissionDenied("Комментировать эту заявку нельзя")

    text = request.POST.get('text', '').strip()
    if text:
        ApplicationComment.objects.create(application=application, author=request.user, text=text[:2000])
    return _after_post(request, application)
