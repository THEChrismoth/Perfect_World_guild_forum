"""Данные для дашборда на главной странице админ-панели.

Каждый блок показывается только тем, у кого есть права на соответствующий раздел;
состояние резервных копий и настроек сайта — только суперпользователям.
"""
from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.urls import reverse
from django.utils import timezone

GUILD_GROUP = 'Член гильдии'


def _url(name, query=''):
    return reverse(name) + (f'?{query}' if query else '')


def _stat(icon, label, value, url=None, hint='', tone='accent'):
    return {'icon': icon, 'label': label, 'value': value, 'url': url, 'hint': hint, 'tone': tone}


def _alert(level, text, url=None, action=''):
    return {'level': level, 'text': text, 'url': url, 'action': action}


def build_dashboard(request):
    user = request.user
    now = timezone.now()
    week_ago = now - timedelta(days=7)
    can = user.has_perm

    stats, alerts, actions = [], [], []
    recent_applications, new_users = [], []

    # ----- Игроки -----
    if can('auth.view_user'):
        total = User.objects.count()
        new_week = User.objects.filter(date_joined__gte=week_ago).count()
        guild_group = Group.objects.filter(name=GUILD_GROUP).first()
        guild = guild_group.user_set.count() if guild_group else 0
        stats.append(_stat('👥', 'Пользователи', total, _url('admin:auth_user_changelist'),
                           f'+{new_week} за неделю' if new_week else 'новых за неделю нет'))
        # Фильтр админки по группе — groups__id__exact (как в боковом фильтре списка пользователей)
        guild_url = _url('admin:auth_user_changelist', f'groups__id__exact={guild_group.pk}') if guild_group else None
        stats.append(_stat('🛡️', 'Члены гильдии', guild, guild_url,
                           '' if guild_group else f'создайте группу «{GUILD_GROUP}»', tone='success'))
        new_users = list(User.objects.order_by('-date_joined')[:5])

    # ----- Заявки -----
    if can('reception.view_application'):
        from reception.models import Application

        pending = Application.objects.filter(status='pending').count()
        voting = Application.objects.filter(status='voting').count()
        stats.append(_stat('📝', 'Заявки на рассмотрении', pending,
                           _url('admin:reception_application_changelist', 'status__exact=pending'),
                           f'{voting} на голосовании', tone='warning' if pending else 'accent'))
        if pending:
            alerts.append(_alert('warning', f'Новые заявки в гильдию ждут проверки: {pending}',
                                 _url('admin:reception_application_changelist', 'status__exact=pending'), 'Проверить'))
        recent_applications = list(Application.objects.select_related('user').order_by('-created_at')[:5])

    # ----- Аукцион -----
    if can('auction.view_auctionlot'):
        from auction.models import AuctionLot

        active = AuctionLot.objects.filter(status='active')
        expired = active.filter(end_date__lte=now).count()
        stats.append(_stat('🎯', 'Активные лоты', active.count(),
                           _url('admin:auction_auctionlot_changelist', 'status__exact=active'),
                           f'{expired} ждут завершения' if expired else 'идут торги'))
        if expired:
            alerts.append(_alert('warning', f'Время торгов истекло, лоты ждут завершения: {expired}',
                                 _url('admin:auction_auctionlot_changelist', 'status__exact=active'), 'Завершить'))

    # ----- Форум -----
    if can('forum.view_post'):
        from forum.models import Post, Topic

        posts_week = Post.objects.filter(created_at__gte=week_ago).count()
        stats.append(_stat('💬', 'Темы на форуме', Topic.objects.count(), _url('admin:forum_topic_changelist'),
                           f'{posts_week} сообщений за неделю'))

    # ----- Ивенты -----
    if can('events.view_eventnotification'):
        from events.models import EventNotification

        upcoming = EventNotification.objects.filter(event_date__gte=now.date()).count()
        stats.append(_stat('⚔️', 'Ближайшие ивенты', upcoming,
                           _url('admin:events_eventnotification_changelist'), 'приглашения на будущие даты'))

    # ----- Онлайн -----
    from forum.models import get_online_users
    stats.append(_stat('🟢', 'Сейчас на сайте', get_online_users().count(), hint='за последние 5 минут', tone='success'))

    # ----- Служебное: только суперпользователь -----
    if user.is_superuser:
        alerts.extend(_system_alerts(now))

    # ----- Быстрые действия -----
    actions.append({'icon': '📊', 'label': 'Таблица активности', 'url': _url('admin:activity_management')})
    if can('auction.add_auctionlot'):
        actions.append({'icon': '🎯', 'label': 'Новый лот', 'url': _url('admin:auction_auctionlot_add')})
    if can('events.add_eventnotification'):
        actions.append({'icon': '📢', 'label': 'Пригласить на ивент', 'url': _url('admin:events_eventnotification_add')})
    if can('forum.add_category'):
        actions.append({'icon': '🗂️', 'label': 'Разделы форума', 'url': _url('admin:forum_subcategory_changelist')})
    if user.is_superuser:
        actions.append({'icon': '💾', 'label': 'Сделать резервную копию', 'url': _url('admin:backups_backup_run'), 'post': True})
        actions.append({'icon': '⚙️', 'label': 'Настройки сайта', 'url': _url('admin:core_sitesettings_changelist')})
    actions.append({'icon': '🌐', 'label': 'Открыть сайт', 'url': '/', 'external': True})

    return {
        'stats': stats,
        'alerts': alerts,
        'actions': actions,
        'recent_applications': recent_applications,
        'new_users': new_users,
        'backup': _backup_summary() if user.is_superuser else None,
    }


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
    # Бот хотя бы раз подключался, а теперь молчит — TeamSpeak включён, но задачи не выполняются
    if ts_settings.bot_last_seen and not ts_settings.bot_online:
        alerts.append(_alert('danger', 'Бот TeamSpeak не на связи: доступы и комнаты не выдаются, посещение ивентов не учитывается',
                             _url('admin:teamspeak_teamspeaksettings_changelist'), 'Подробнее'))
    failed = TsTask.objects.filter(status='failed', finished_at__gte=now - timedelta(days=1)).count()
    if failed:
        alerts.append(_alert('warning', f'Задачи бота TeamSpeak с ошибкой за сутки: {failed}',
                             _url('admin:teamspeak_tstask_changelist', 'status__exact=failed'), 'Журнал'))
    return alerts
