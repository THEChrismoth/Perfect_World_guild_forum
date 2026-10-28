"""Данные для дашборда на главной странице админ-панели.

Каждый блок показывается только тем, у кого есть права на соответствующий раздел;
состояние резервных копий и настроек сайта — только суперпользователям.
Иконки — имена из core/templatetags/ga_admin.py.
"""
import math
from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.urls import reverse
from django.utils import timezone

GUILD_GROUP = 'Член гильдии'
CHART_DAYS = 14

# Размеры области графика в единицах viewBox (растягивается по ширине карточки).
CHART_WIDTH, CHART_HEIGHT, CHART_TOP = 600, 220, 12


def _url(name, query=''):
    return reverse(name) + (f'?{query}' if query else '')


def _trend(current, previous):
    """Изменение за неделю к прошлой неделе в процентах: None, если сравнивать не с чем."""
    if not previous:
        return None
    return round((current - previous) * 100 / previous)


def _stat(icon, label, value, url=None, hint='', trend=None):
    return {'icon': icon, 'label': label, 'value': value, 'url': url, 'hint': hint, 'trend': trend}


def _alert(level, text, url=None, action=''):
    return {'level': level, 'text': text, 'url': url, 'action': action}


def build_dashboard(request):
    user = request.user
    now = timezone.now()
    week_ago = now - timedelta(days=7)
    two_weeks_ago = now - timedelta(days=14)
    can = user.has_perm

    stats, alerts, actions, series, feed = [], [], [], [], []
    applications_chart = None

    # ----- Игроки -----
    if can('auth.view_user'):
        total = User.objects.count()
        new_week = User.objects.filter(date_joined__gte=week_ago).count()
        new_prev = User.objects.filter(date_joined__gte=two_weeks_ago, date_joined__lt=week_ago).count()
        guild_group = Group.objects.filter(name=GUILD_GROUP).first()
        guild = guild_group.user_set.count() if guild_group else 0
        stats.append(_stat('users', 'Пользователи', total, _url('admin:auth_user_changelist'),
                           f'+{new_week} за неделю' if new_week else 'новых за неделю нет', _trend(new_week, new_prev)))
        # Фильтр админки по группе — groups__id__exact (как в боковом фильтре списка пользователей).
        guild_url = _url('admin:auth_user_changelist', f'groups__id__exact={guild_group.pk}') if guild_group else None
        stats.append(_stat('shield', 'Члены гильдии', guild, guild_url,
                           '' if guild_group else f'создайте группу «{GUILD_GROUP}»'))
        series.append(_series('users', 'Регистрации', User.objects.all(), 'date_joined', now))
        for new_user in User.objects.order_by('-date_joined')[:5]:
            feed.append(_feed('user-plus', f'Новый пользователь {new_user.username}', new_user.date_joined,
                              reverse('admin:auth_user_change', args=[new_user.pk]),
                              '' if new_user.is_active else 'не подтверждён'))

    # ----- Заявки -----
    if can('reception.view_application'):
        from reception.models import Application

        pending = Application.objects.filter(status='pending').count()
        voting = Application.objects.filter(status='voting').count()
        stats.append(_stat('file-text', 'Заявки на рассмотрении', pending,
                           _url('admin:reception_application_changelist', 'status__exact=pending'),
                           f'{voting} на голосовании'))
        if pending:
            alerts.append(_alert('warning', f'Новые заявки в гильдию ждут проверки: {pending}',
                                 _url('admin:reception_application_changelist', 'status__exact=pending'), 'Проверить'))
        series.append(_series('applications', 'Заявки', Application.objects.all(), 'created_at', now))
        applications_chart = _applications_chart(Application)
        for application in Application.objects.select_related('user').order_by('-created_at')[:5]:
            feed.append(_feed('file-text', f'Заявка от {application.user.username}', application.created_at,
                              reverse('admin:reception_application_change', args=[application.pk]),
                              application.get_status_display()))

    # ----- Аукцион -----
    if can('auction.view_auctionlot'):
        from auction.models import AuctionLot

        active = AuctionLot.objects.filter(status='active')
        expired = active.filter(end_date__lte=now).count()
        stats.append(_stat('gavel', 'Активные лоты', active.count(),
                           _url('admin:auction_auctionlot_changelist', 'status__exact=active'),
                           f'{expired} ждут завершения' if expired else 'идут торги'))
        if expired:
            alerts.append(_alert('warning', f'Время торгов истекло, лоты ждут завершения: {expired}',
                                 _url('admin:auction_auctionlot_changelist', 'status__exact=active'), 'Завершить'))

    # ----- Форум -----
    if can('forum.view_post'):
        from forum.models import Post, Topic

        posts_week = Post.objects.filter(created_at__gte=week_ago).count()
        posts_prev = Post.objects.filter(created_at__gte=two_weeks_ago, created_at__lt=week_ago).count()
        stats.append(_stat('message', 'Темы на форуме', Topic.objects.count(), _url('admin:forum_topic_changelist'),
                           f'{posts_week} сообщений за неделю', _trend(posts_week, posts_prev)))
        series.append(_series('posts', 'Сообщения', Post.objects.all(), 'created_at', now))
        for topic in Topic.objects.select_related('author').order_by('-created_at')[:5]:
            feed.append(_feed('message', f'Новая тема «{topic.title}»', topic.created_at,
                              reverse('admin:forum_topic_change', args=[topic.pk]), topic.author.username))

    # ----- Ивенты -----
    if can('events.view_eventnotification'):
        from events.models import EventNotification

        upcoming = EventNotification.objects.filter(event_date__gte=now.date()).count()
        stats.append(_stat('swords', 'Ближайшие ивенты', upcoming,
                           _url('admin:events_eventnotification_changelist'), 'приглашения на будущие даты'))

    # ----- Онлайн -----
    from forum.models import get_online_users
    stats.append(_stat('radio', 'Сейчас на сайте', get_online_users().count(), hint='за последние 5 минут'))

    # ----- Служебное: только суперпользователь -----
    if user.is_superuser:
        alerts.extend(_system_alerts(now))

    # ----- Быстрые действия -----
    actions.append({'icon': 'table', 'label': 'Таблица активности', 'url': _url('admin:activity_management')})
    if can('auction.add_auctionlot'):
        actions.append({'icon': 'gavel', 'label': 'Новый лот', 'url': _url('admin:auction_auctionlot_add')})
    if can('events.add_eventnotification'):
        actions.append({'icon': 'megaphone', 'label': 'Пригласить на ивент', 'url': _url('admin:events_eventnotification_add')})
    if can('forum.add_category'):
        actions.append({'icon': 'folder', 'label': 'Разделы форума', 'url': _url('admin:forum_subcategory_changelist')})
    if user.is_superuser:
        actions.append({'icon': 'database', 'label': 'Сделать резервную копию', 'url': _url('admin:backups_backup_run'), 'post': True})
        actions.append({'icon': 'settings', 'label': 'Настройки сайта', 'url': _url('admin:core_sitesettings_changelist')})
    actions.append({'icon': 'globe', 'label': 'Открыть сайт', 'url': '/', 'external': True})

    feed.sort(key=lambda item: item['time'], reverse=True)

    return {
        'stats': stats,
        'alerts': alerts,
        'actions': actions,
        'activity_chart': _activity_chart(series, now) if series else None,
        'applications_chart': applications_chart,
        'feed': feed[:8],
        'backup': _backup_summary() if user.is_superuser else None,
    }


def _feed(icon, text, time, url, note=''):
    return {'icon': icon, 'text': text, 'time': time, 'url': url, 'note': note}


# ----- Графики -----

def _series(key, label, queryset, field, now):
    """Количество записей по дням: текущие CHART_DAYS дней и столько же до них — для сравнения."""
    today = timezone.localdate(now)
    start = today - timedelta(days=CHART_DAYS * 2 - 1)
    counts = dict(
        queryset.filter(**{f'{field}__date__gte': start})
        .annotate(day=TruncDate(field)).values('day').annotate(n=Count('pk')).values_list('day', 'n')
    )
    days = [start + timedelta(days=offset) for offset in range(CHART_DAYS * 2)]
    values = [counts.get(day, 0) for day in days]
    return {
        'key': key,
        'label': label,
        'days': days[CHART_DAYS:],
        'current': values[CHART_DAYS:],
        'previous': values[:CHART_DAYS],
    }


def _nice_top(value):
    """Верх шкалы: «круглое» число не меньше value, которое делится на 4 деления."""
    if value <= 4:
        return 4
    step = value / 4
    magnitude = 10 ** math.floor(math.log10(step))
    for factor in (1, 2, 5, 10):
        if step <= factor * magnitude:
            return factor * magnitude * 4


def _points(values, top):
    last = len(values) - 1
    return [(index * CHART_WIDTH / last, CHART_HEIGHT - value / top * (CHART_HEIGHT - CHART_TOP))
            for index, value in enumerate(values)]


def _tick(value, top):
    """Деление шкалы: y — для линии сетки в SVG, top — для подписи в процентах высоты."""
    y = CHART_HEIGHT - value / top * (CHART_HEIGHT - CHART_TOP)
    return {'value': value, 'y': y, 'top': y / CHART_HEIGHT * 100}


def _smooth_path(points):
    """Плавная линия через точки; горизонтальные касательные не дают ей уйти ниже нуля."""
    x, y = points[0]
    path = [f'M{x:.1f},{y:.1f}']
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        middle = (x0 + x1) / 2
        path.append(f'C{middle:.1f},{y0:.1f} {middle:.1f},{y1:.1f} {x1:.1f},{y1:.1f}')
    return ' '.join(path)


def _activity_chart(series, now):
    panels = []
    for item in series:
        top = _nice_top(max(item['current'] + item['previous']))
        current = _points(item['current'], top)
        line = _smooth_path(current)
        panels.append({
            'key': item['key'],
            'label': item['label'],
            'total': sum(item['current']),
            'previous_total': sum(item['previous']),
            'trend': _trend(sum(item['current']), sum(item['previous'])),
            'line': line,
            'area': f'{line} L{CHART_WIDTH},{CHART_HEIGHT} L0,{CHART_HEIGHT} Z',
            'previous_line': _smooth_path(_points(item['previous'], top)),
            'ticks': [_tick(top // 4 * step, top) for step in range(4, -1, -1)],
            'dots': [{'left': x / CHART_WIDTH * 100, 'top': y / CHART_HEIGHT * 100, 'value': value, 'day': day}
                     for (x, y), value, day in zip(current, item['current'], item['days'])],
        })
    days = series[0]['days']
    return {
        'width': CHART_WIDTH,
        'height': CHART_HEIGHT,
        'panels': panels,
        # Подписи по оси X — через день, чтобы не налезали друг на друга.
        'labels': [{'left': index / (len(days) - 1) * 100, 'day': day}
                   for index, day in enumerate(days) if index % 2 == (len(days) - 1) % 2],
    }


APPLICATION_STATUS_ORDER = ('pending', 'voting', 'approved', 'rejected')


def _applications_chart(Application):
    counts = dict(Application.objects.values('status').annotate(n=Count('pk')).values_list('status', 'n'))
    names = dict(Application.STATUS_CHOICES)
    total = sum(counts.values())
    segments, offset = [], 0
    for status in APPLICATION_STATUS_ORDER:
        count = counts.get(status, 0)
        share = count * 100 / total if total else 0
        # Окружность r=15.915 имеет длину 100, поэтому доли в процентах сразу идут в stroke-dasharray.
        # Отсчёт от 12 часов: смещение 25.
        segments.append({'status': status, 'label': names[status], 'count': count,
                         'share': round(share), 'dash': share, 'offset': 25 - offset})
        offset += share
    return {'total': total, 'segments': segments}


# ----- Служебное -----

def _backup_summary():
    from backups.crypto import encryption_enabled
    from backups.models import Backup, BackupSettings

    backup_settings = BackupSettings.load()
    last = Backup.objects.exclude(status__in=('pending', 'running')).order_by('-created_at').first()
    last_ok = Backup.objects.filter(status__in=Backup.COMPLETED_STATUSES).order_by('-created_at').first()
    return {
        'enabled': backup_settings.enabled,
        'encrypted': encryption_enabled(),
        'yandex': backup_settings.yandex_configured,
        'last': last,
        'last_ok': last_ok,
        'journal_url': _url('admin:backups_backup_changelist'),
        'settings_url': _url('admin:backups_backupsettings_changelist'),
    }


def _system_alerts(now):
    from backups.crypto import encryption_enabled
    from backups.models import Backup, BackupSettings
    from .models import SiteSettings

    alerts = []
    site = SiteSettings.load()
    backup_settings = BackupSettings.load()
    backups_url = _url('admin:backups_backupsettings_changelist')
    site_url = _url('admin:core_sitesettings_changelist')

    last = Backup.objects.exclude(status__in=('pending', 'running')).order_by('-created_at').first()
    last_ok = Backup.objects.filter(status__in=Backup.COMPLETED_STATUSES).order_by('-created_at').first()

    if not backup_settings.enabled:
        alerts.append(_alert('danger', 'Автоматические резервные копии выключены', backups_url, 'Включить'))
    elif last_ok is None or last_ok.created_at < now - timedelta(days=8):
        alerts.append(_alert('danger', 'Больше недели не было успешной резервной копии',
                             _url('admin:backups_backup_changelist'), 'Журнал'))
    if last and last.status in ('failed', 'warning'):
        alerts.append(_alert('danger' if last.status == 'failed' else 'warning',
                             f'Последняя резервная копия: {last.get_status_display().lower()}',
                             reverse('admin:backups_backup_change', args=[last.pk]), 'Подробнее'))
    if not encryption_enabled():
        alerts.append(_alert('warning', 'Резервные копии не шифруются — задайте BACKUP_ENCRYPTION_PASSWORD в .env',
                             backups_url, 'Как включить'))
    if backup_settings.yandex_token_unreadable or site.secret_unreadable('email_host_password') \
            or site.secret_unreadable('captcha_private_key'):
        alerts.append(_alert('danger', 'Сохранённые пароли или ключи не расшифровываются (сменился DJANGO_SECRET_KEY) '
                                       '— введите их заново', site_url, 'Настройки'))
    if not site.email_configured:
        alerts.append(_alert('info', 'Почта не настроена: письма сайта не отправляются', site_url, 'Настроить'))

    from teamspeak.models import TeamSpeakSettings, TsTask
    ts_settings = TeamSpeakSettings.load()
    # Бот хотя бы раз подключался, а теперь молчит — TeamSpeak включён, но задачи не выполняются.
    if ts_settings.bot_last_seen and not ts_settings.bot_online:
        alerts.append(_alert('danger', 'Бот TeamSpeak не на связи: доступы и комнаты не выдаются, посещение ивентов не учитывается',
                             _url('admin:teamspeak_teamspeaksettings_changelist'), 'Подробнее'))
    failed = TsTask.objects.filter(status='failed', finished_at__gte=now - timedelta(days=1)).count()
    if failed:
        alerts.append(_alert('warning', f'Задачи бота TeamSpeak с ошибкой за сутки: {failed}',
                             _url('admin:teamspeak_tstask_changelist', 'status__exact=failed'), 'Журнал'))
    return alerts
