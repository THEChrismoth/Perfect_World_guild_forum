"""Главная страница гильдии: личные задачи и доступная пользователю активность."""
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Count, Exists, Max, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from auction.models import AuctionBid, AuctionLot
from events.models import EventAttendance, EventNotification, EventRosterEntry
from forum.models import SubCategory, Topic
from reception.models import Application, ApplicationVote
from .roles import GUILD_GROUP, is_guild_member


def recent_topics(user):
    """Возвращает обсуждения только из доступных категорий и подкатегорий."""
    sections = SubCategory.objects.select_related('category').prefetch_related('view_groups', 'category__view_groups')
    allowed = [section.pk for section in sections if section.is_visible_to_user(user)]
    return (Topic.objects.filter(subcategory_id__in=allowed).select_related('author', 'subcategory')
            .annotate(posts_total=Count('posts'), last_activity=Coalesce(Max('posts__created_at'), 'updated_at'))
            .order_by('-last_activity', '-pk')[:6])


def member_data(user, include_all_events=False):
    """Собирает предстоящие приглашения, торги и голосования без изменения данных."""
    now = timezone.now()
    answers = EventAttendance.objects.filter(notification_id=OuterRef('pk'), user=user)
    slots = EventRosterEntry.objects.filter(notification_id=OuterRef('pk'), user=user)
    invited = EventNotification.objects.filter(pk=OuterRef('pk'), sent_to_users=user)
    dates = (EventNotification.objects.filter(sent_at__isnull=False, event_type__is_active=True,
             event_date__gte=timezone.localdate(), points_processed_at__isnull=True)
             .select_related('event_type').annotate(my_answer=Subquery(answers.values('status')[:1]),
                 my_comment=Subquery(answers.values('comment')[:1]), is_invited=Exists(invited),
                 my_party=Subquery(slots.values('party_number')[:1]))
             .order_by('event_date', 'start_time', 'pk'))
    if not include_all_events:
        dates = dates.filter(sent_to_users=user)
    visible_dates = [date for date in dates.iterator(chunk_size=50) if date.response_open]
    upcoming = visible_dates[:2]
    bids = AuctionBid.objects.filter(lot_id=OuterRef('pk'))
    lots = (AuctionLot.objects.filter(status='active', start_date__lte=now)
            .filter(Q(end_date__gt=now) | Q(end_date__isnull=True))
            .annotate(my_bid=Subquery(bids.filter(bidder=user).order_by('-bid_amount').values('bid_amount')[:1]),
                      leader_id=Subquery(bids.filter(is_frozen=True).order_by('-bid_amount', 'created_at').values('bidder_id')[:1]))
            .order_by('end_date', '-created_at'))
    outbid = lots.filter(my_bid__isnull=False).exclude(leader_id=user.pk).count()
    voting = Application.objects.filter(status='voting', approved_at__isnull=False).annotate(
        already_voted=Exists(ApplicationVote.objects.filter(application_id=OuterRef('pk'), voter=user)))
    unvoted = voting.filter(already_voted=False).count()
    profile = user.profile
    available = profile.get_available_points()
    guild = User.objects.filter(is_active=True, groups__name=GUILD_GROUP).aggregate(
        total=Count('pk', distinct=True),
        online=Count('pk', filter=Q(profile__last_activity__gte=now - timedelta(minutes=5)), distinct=True))
    return {'upcoming': upcoming, 'featured_event': upcoming[0] if upcoming else None,
            'upcoming_total': len(visible_dates), 'guild_online': guild['online'], 'guild_total': guild['total'],
            'unanswered_events': sum(date.is_invited and not date.my_answer for date in visible_dates),
            'lots': [], 'lots_total': lots.count(), 'outbid_count': outbid,
            'voting_count': unvoted, 'available_points': available,
            'frozen_points': profile.activity_points - available, 'transactions': []}


@login_required
def home(request):
    """Показывает главную с учётом членства, прав и личных задач игрока."""
    user = request.user
    member = is_guild_member(user)
    management = member and user.is_staff
    data = {'is_member': member, 'is_management_home': management,
            'topics': [] if member else recent_topics(user), 'today': timezone.localdate(),
            'profile': user.profile, 'quick_actions': [], 'attention': []}
    if member:
        include_all = management and any(user.has_perm(f'events.{action}_eventnotification')
                                         for action in ('view', 'change', 'add'))
        data.update(member_data(user, include_all_events=include_all))
        from skirmishes.views import widget_data
        data.update(widget_data(user))
        if data['unanswered_events']:
            data['attention'].append({'icon': 'calendar', 'title': 'Сообщите о планах участия',
                'text': f"Ближайших ивентов без ответа: {data['unanswered_events']}", 'url': reverse('events:event_index')})
        if data['outbid_count']:
            data['attention'].append({'icon': 'gavel', 'title': 'Вашу ставку перебили',
                'text': f"Торгов с перебитой ставкой: {data['outbid_count']}", 'url': reverse('auction:my_bids')})
        if data['voting_count']:
            data['attention'].append({'icon': 'file-text', 'title': 'Кандидаты ждут вашего голоса',
                'text': f"Открытых голосований без вашего ответа: {data['voting_count']}",
                'url': reverse('reception:application_list')})
    else:
        gear = user.profile.main_gear()
        data['profile_ready'] = bool(user.profile.player_class) and not gear.is_empty()
        data['my_application'] = Application.objects.filter(user=user).order_by('-created_at', '-pk').first()
    if user.is_staff:
        for permission, label, icon, route in [
            ('events.add_eventtype', 'Создать ивент', 'plus', 'admin:events_eventtype_add'),
            ('auction.add_auctionlot', 'Создать лот', 'gavel', 'admin:auction_auctionlot_add'),
        ]:
            if not management and user.has_perm(permission):
                data['quick_actions'].append({'label': label, 'icon': icon, 'url': reverse(route)})
        if user.has_perm('reception.view_application'):
            pending = Application.objects.filter(status='pending').count()
            data['pending_applications'] = pending
            if pending:
                data['attention'].insert(0, {'icon': 'file-text', 'title': 'Новые заявки в гильдию',
                    'text': f'Ожидают проверки: {pending}', 'url': reverse('admin:reception_application_changelist')})
    if management:
        from .home_management import management_data
        data.update(management_data(user))
    template = 'core/home_dashboard.html' if member else 'core/home.html'
    return render(request, template, data)
