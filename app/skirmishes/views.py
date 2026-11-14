from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Exists, OuterRef
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from core.models import SiteSettings
from core.roles import guild_member_required
from .forms import CorrectionForm, JoinForm, StartForm
from .models import AttendanceCorrection, Participant, Skirmish
from .services import (
    can_manage, confirm_results, correct_attendance, finish_skirmish,
    join_by_code, require_manager, start_skirmish,
)


def _errors(request, error):
    for text in error.messages:
        messages.error(request, text)


def widget_data(user):
    """Данные общего блока на главной и в списке без запроса на каждого участника."""
    current = Skirmish.objects.filter(ended_at__isnull=True).annotate(total=Count('participants')).first()
    participant = Participant.objects.filter(skirmish=current, user=user).select_related('skirmish').first() if current else None
    return {'active_skirmish': current, 'my_skirmish_participation': participant, 'can_manage_skirmishes': can_manage(user),
            'skirmish_join_form': JoinForm()}


@login_required
@guild_member_required
def index(request):
    selected = request.GET.get('filter', 'all')
    sessions = (Skirmish.objects.select_related('organizer').annotate(total=Count('participants'))
                .order_by('-started_at', '-pk'))
    if selected == 'active':
        sessions = sessions.filter(ended_at__isnull=True)
    elif selected == 'finished':
        sessions = sessions.filter(ended_at__isnull=False)
    elif selected == 'mine':
        sessions = sessions.annotate(mine=Exists(Participant.objects.filter(
            skirmish_id=OuterRef('pk'), user=request.user))).filter(mine=True)
    else:
        selected = 'all'
    data = widget_data(request.user)
    data.update(page=Paginator(sessions, 20).get_page(request.GET.get('page')), selected_filter=selected,
                start_form=StartForm(), skirmish_join_form=JoinForm(initial={'code': request.GET.get('code', '')}))
    if data['can_manage_skirmishes']:
        data['channel_configured'] = bool(SiteSettings.load().skirmish_ts_channel.strip())
    return render(request, 'skirmishes/index.html', data)


@login_required
@guild_member_required
@require_POST
def start(request):
    require_manager(request.user)
    form = StartForm(request.POST)
    if form.is_valid():
        try:
            session, created = start_skirmish(request.user, form.cleaned_data['title'])
            if created:
                messages.success(request, 'Замес начат. Поделитесь кодом и переходите в TS.')
            return redirect(session)
        except ValidationError as error:
            _errors(request, error)
    else:
        messages.error(request, 'Название должно быть не длиннее 120 символов.')
    return redirect('skirmishes:index')


@login_required
@guild_member_required
@require_POST
def join(request):
    form = JoinForm(request.POST)
    if form.is_valid():
        try:
            entry = join_by_code(request.user, form.cleaned_data['code'])
            messages.success(request, 'Вы присоединились к сбору. Присутствие учитывается в TeamSpeak.')
            return redirect(entry.skirmish)
        except ValidationError as error:
            _errors(request, error)
    else:
        messages.error(request, 'Введите четырёхзначный код замеса.')
    return redirect('skirmishes:index')


@login_required
@guild_member_required
def detail(request, pk):
    session = get_object_or_404(Skirmish.objects.select_related('organizer', 'reviewed_by'), pk=pk)
    manager = can_manage(request.user)
    entries = list(session.participants.select_related('user', 'skirmish').order_by('user__username'))
    return render(request, 'skirmishes/detail.html', {
        'skirmish': session, 'participants': entries, 'can_manage_skirmishes': manager,
        'attended_count': sum(entry.attended for entry in entries),
        'my_entry': next((entry for entry in entries if entry.user_id == request.user.pk), None),
        'unidentified': session.unidentified.order_by('nickname', 'pk') if manager else [],
        'corrections': AttendanceCorrection.objects.filter(participant__skirmish=session)
            .select_related('actor', 'participant__user') if manager else [],
        'correction_form': CorrectionForm(skirmish=session) if manager and not session.active and not session.reviewed_at else None,
        'report_stale': session.active and (not session.last_report_at or timezone.now() - session.last_report_at > timedelta(minutes=2)),
        'share_url': request.build_absolute_uri(reverse('skirmishes:index')) + f'?code={session.code}',
    })


@login_required
@guild_member_required
@require_http_methods(['GET', 'POST'])
def finish(request, pk):
    require_manager(request.user)
    session = get_object_or_404(Skirmish, pk=pk)
    if request.method == 'POST':
        finish_skirmish(session.pk, request.user)
        messages.success(request, 'Замес завершён. Проверьте участие и подтвердите итоги.')
        return redirect(session)
    return render(request, 'skirmishes/finish.html', {'skirmish': session})


@login_required
@guild_member_required
@require_POST
def confirm(request, pk):
    require_manager(request.user)
    session = get_object_or_404(Skirmish, pk=pk)
    try:
        confirm_results(session.pk, request.user)
        messages.success(request, 'Итоги подтверждены.')
    except ValidationError as error:
        _errors(request, error)
    return redirect(session)


@login_required
@guild_member_required
@require_POST
def correct(request, pk):
    require_manager(request.user)
    session = get_object_or_404(Skirmish, pk=pk)
    form = CorrectionForm(request.POST, skirmish=session)
    if form.is_valid():
        try:
            correct_attendance(session.pk, request.user, form.cleaned_data['user'],
                {'yes': True, 'no': False, 'auto': None}[form.cleaned_data['result']], form.cleaned_data['reason'])
            messages.success(request, 'Решение сохранено в истории корректировок.')
            return redirect(session)
        except ValidationError as error:
            form.add_error(None, error)
    return render(request, 'skirmishes/correction.html', {'skirmish': session, 'form': form}, status=400)
