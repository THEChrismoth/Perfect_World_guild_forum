"""Главная страница гильдии: личные задачи и доступная пользователю активность."""
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Exists, Max, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from auction.models import AuctionBid, AuctionLot
from events.models import EventAttendance, EventNotification, EventRosterEntry
from forum.models import SubCategory, Topic
from reception.models import Application, ApplicationVote
from .roles import is_guild_member


def recent_topics(user):
    """Возвращает обсуждения только из доступных категорий и подкатегорий."""
    sections = SubCategory.objects.select_related('category').prefetch_related('view_groups', 'category__view_groups')
    allowed = [section.pk for section in sections if section.is_visible_to_user(user)]
    return (Topic.objects.filter(subcategory_id__in=allowed).select_related('author', 'subcategory')
            .annotate(posts_total=Count('posts'), last_activity=Coalesce(Max('posts__created_at'), 'updated_at'))
            .order_by('-last_activity', '-pk')[:6])


def member_data(user):
    """Собирает предстоящие приглашения, торги и голосования без изменения данных."""
    now = timezone.now()
    answers = EventAttendance.objects.filter(notification_id=OuterRef('pk'), user=user)
    slots = EventRosterEntry.objects.filter(notification_id=OuterRef('pk'), user=user)
    dates = (EventNotification.objects.filter(sent_at__isnull=False, event_type__is_active=True,
             event_date__gte=timezone.localdate(), sent_to_users=user, points_processed_at__isnull=True)
             .select_related('event_type').annotate(my_answer=Subquery(answers.values('status')[:1]),
                 my_party=Subquery(slots.values('party_number')[:1]))
             .order_by('event_date', 'start_time', 'pk'))
    upcoming = [date for date in dates[:12] if date.response_open][:3]
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
    transactions = user.points_transactions.order_by('-created_at', '-pk')[:3]
    return {'upcoming': upcoming, 'featured_event': upcoming[0] if upcoming else None,
            'unanswered_events': sum(not date.my_answer for date in upcoming),
            'lots': list(lots[:3]), 'lots_total': lots.count(), 'outbid_count': outbid,
            'voting_count': unvoted, 'available_points': available,
            'frozen_points': profile.activity_points - available, 'transactions': transactions}


@login_required
def home(request):
    """Показывает главную с учётом членства, прав и личных задач игрока."""
    user = request.user
    member = is_guild_member(user)
    data = {'is_member': member, 'topics': recent_topics(user), 'today': timezone.localdate(),
            'profile': user.profile, 'quick_actions': [], 'attention': []}
    if member:
        data.update(member_data(user))
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
            if user.has_perm(permission):
                data['quick_actions'].append({'label': label, 'icon': icon, 'url': reverse(route)})
        if user.has_perm('reception.view_application'):
            pending = Application.objects.filter(status='pending').count()
            data['pending_applications'] = pending
            if pending:
                data['attention'].insert(0, {'icon': 'file-text', 'title': 'Новые заявки в гильдию',
                    'text': f'Ожидают проверки: {pending}', 'url': reverse('admin:reception_application_changelist')})
    return render(request, 'core/home.html', data)
