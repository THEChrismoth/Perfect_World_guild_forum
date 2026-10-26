"""Заполняет базу вымышленной гильдией для демо-сайта.

Стирает ВСЮ базу, поэтому работает только при DEMO_MODE=True. Где можно, данные создаются
настоящей логикой сайта (ставки, завершение аукциона, начисление очков за ивенты), чтобы
демо показывало то же, что увидит гильдия на своем сервере.
"""
import datetime
import random

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from auction.models import AuctionLot, PointsTransaction
from auction.views import place_bid
from core.models import SiteSettings
from demo.guests import admin_group, fill_profile
from events.models import Event, EventAttendance, EventNotification, EventType, PartyMember
from events.utils import send_event_notification
from forum.models import Category, Post, SubCategory, Topic
from koslist.models import Guild, Player
from reception.models import Application, ApplicationVote
from teamspeak.attendance import finalize
from teamspeak.models import GUILD_GROUP, EventPresence, TsLink

GUILD_NAME = 'Северный Ветер'

# Ник, класс. Первые — администраторы и лидеры отрядов.
MEMBERS = [
    ('Северянка', 'zhrec'), ('Каратель', 'var'), ('Тень_Ветра', 'sin'), ('Лунный_Свет', 'mag'),
    ('Гром', 'obor'), ('Искра', 'luk'), ('Вереск', 'dru'), ('Сокол', 'strel'),
    ('Шёпот', 'priz'), ('Аметист', 'mist'), ('Полярник', 'strazh'), ('Рысь', 'zhnec'),
    ('Феникс', 'pal'), ('Мираж', 'sham'), ('Багровый', 'dk'), ('Кочевник', 'makaka'),
    ('Мелодия', 'bard'),
]
# Подавшие заявки, но не вступившие.
APPLICANTS = [('Странник_Ночи', 'luk'), ('Кремень', 'var'), ('Ржавый', 'sin')]

# Ивент: название, адрес, иконка, описание, отрядов, размер, канал TS, очки за участие, штраф.
EVENT_TYPES = [
    ('ТВ', 'tv', '⚔️', 'Территориальные войны: атака и защита территорий гильдии.', 2, 10, 'Гильдия / ТВ', 10, 5),
    ('КХ', 'kh', '🏰', 'Поход гильдии на КХ. Лут распределяется через аукцион.', 1, 10, 'Гильдия / КХ', 15, 5),
    ('Мировой босс', 'world-boss', '🐉', 'Сбор на мирового босса.', 1, 10, 'Гильдия / Боссы', 5, 0),
]


class DemoMessages:
    """Заменяет хранилище сообщений: place_bid пишет в него, как в обычном запросе."""

    def add(self, level, message, extra_tags=''):
        pass


class DemoRequest:
    def __init__(self, user):
        self.user = user
        self._messages = DemoMessages()


class Command(BaseCommand):
    help = 'Стирает базу и заполняет ее вымышленной гильдией для демо-сайта (только при DEMO_MODE=True)'

    def handle(self, *args, **options):
        if not settings.DEMO_MODE:
            raise CommandError('Команда стирает всю базу, поэтому работает только при DEMO_MODE=True')

        self.random = random.Random(42)
        self.now = timezone.now()
        self.today = timezone.localdate()

        # Очистка и заполнение — одна транзакция: при сбросе работающего демо
        # посетители видят старые данные до последнего момента, а не пустую базу.
        with transaction.atomic():
            call_command('flush', interactive=False, verbosity=0)
            SiteSettings.objects.update_or_create(pk=1, defaults={'site_name': f'{GUILD_NAME} · демо'})
            self.create_users()
            self.create_forum()
            self.create_events()
            self.create_auction()
            self.create_reception()
            self.create_koslist()

        self.stdout.write(self.style.SUCCESS(f'Демо-гильдия «{GUILD_NAME}» создана'))

    # ===== Игроки =====

    def make_user(self, username, player_class, days_ago):
        user = User.objects.create(username=username, date_joined=self.now - datetime.timedelta(days=days_ago))
        # Пароля нет: под вымышленными игроками не войти.
        user.set_unusable_password()
        user.save()
        fill_profile(user, player_class, self.random)
        return user

    def create_users(self):
        self.guild_group = Group.objects.create(name=GUILD_GROUP)
        admins = admin_group()

        self.members = [self.make_user(name, cls, self.random.randint(60, 400)) for name, cls in MEMBERS]
        self.applicants = [self.make_user(name, cls, self.random.randint(1, 10)) for name, cls in APPLICANTS]

        # Администраторы: двое первых игроков. Аккаунты посетителей создаются при входе (demo/guests.py).
        self.admin = self.members[0]
        for user in self.members[:2]:
            user.is_staff = True
            user.save(update_fields=['is_staff'])
            user.groups.add(admins)

        self.guild = self.members
        for index, user in enumerate(self.guild):
            user.groups.add(self.guild_group)
            TsLink.objects.create(user=user, uid=f'demo{index:03d}+uid=', status='verified',
                                  token=TsLink.new_token(), verified_at=self.now)
            # Стартовый баланс, дальше очки идут с ивентов и аукциона.
            start = self.random.randint(8, 15) * 10
            user.profile.add_points(start)
            PointsTransaction.objects.create(user=user, amount=start, transaction_type='credit',
                                             description='Очки за прошлый месяц')
        PointsTransaction.objects.update(created_at=self.now - datetime.timedelta(days=30))

    # ===== Форум =====

    def create_forum(self):
        guild_category = Category.objects.create(title='Гильдия', slug='guild', order=1)
        guild_category.view_groups.add(self.guild_group)
        public = Category.objects.create(title='Общий раздел', slug='public', order=2)

        def sub(category, title, slug, order, **flags):
            return SubCategory.objects.create(category=category, title=title, slug=slug, order=order, **flags)

        news = sub(guild_category, 'Объявления', 'news', 1)
        self.events_sub = sub(guild_category, 'Ивенты', 'events', 2, is_events=True)
        sub(guild_category, 'Аукцион', 'auction', 3, is_auction=True)
        sub(guild_category, 'Заявки на вступление', 'applications', 4, is_reception_view=True)
        tactics = sub(guild_category, 'Тактика и гайды', 'tactics', 5)
        sub(public, 'Вступить в гильдию', 'join', 1, is_reception=True)
        tavern = sub(public, 'Таверна', 'tavern', 2)

        leader, admin = self.members[0], self.members[1]
        self.topic(news, 'Расписание ивентов на неделю', leader, 2, [
            (leader, 'ТВ — суббота 20:00, КХ — среда и воскресенье 20:00, мировой босс — по оповещению.\n'
                     'Отмечайтесь в оповещениях «Приду / Не приду», явка считается по TeamSpeak автоматически.'),
            (self.members[5], 'Принято, в среду буду.'),
            (self.members[13], 'В субботу могу опоздать минут на 15.'),
        ])
        self.topic(news, 'Правила распределения лута', admin, 20, [
            (admin, 'Ценный лут с КХ уходит на аукцион за очки активности.\n'
                      'Очки начисляются за участие в ивентах, за пропуск после «Приду» — штраф.'),
            (self.members[3], 'А если ставка перебита — очки возвращаются?'),
            (admin, 'Да, замораживается только ставка лидера. Перебили — очки сразу снова доступны.'),
        ])
        self.topic(tactics, 'Расстановка на ТВ: кто где стоит', self.members[2], 6, [
            (self.members[2], 'Отряд 1 — атака, отряд 2 — защита ворот. Жрецы распределены по отрядам.'),
            (self.members[6], 'Друидов лучше держать во втором, там больше урона по площади.'),
        ])
        self.topic(tavern, 'Скриньте самые смешные моменты с ТВ', self.members[9], 4, [
            (self.members[9], 'Начну: Гром забежал во вражеский отряд и сказал «я на разведку».'),
            (self.members[4], 'Это была тактика!'),
            (self.members[11], '😂'),
        ])

    def topic(self, subcategory, title, author, days_ago, posts):
        topic = Topic.objects.create(subcategory=subcategory, title=title, author=author)
        created = self.now - datetime.timedelta(days=days_ago)
        for index, (post_author, content) in enumerate(posts):
            post = Post.objects.create(topic=topic, author=post_author, content=content)
            Post.objects.filter(pk=post.pk).update(created_at=created + datetime.timedelta(hours=index * 3))
        Topic.objects.filter(pk=topic.pk).update(
            created_at=created, updated_at=created + datetime.timedelta(hours=(len(posts) - 1) * 3))

    # ===== Ивенты =====

    def create_events(self):
        for order, (name, slug, icon, description, parties, size, channel, present, absent) in enumerate(EVENT_TYPES):
            # Адрес задаем сами: slugify отбрасывает кириллицу.
            event_type = EventType.objects.create(
                name=name, slug=slug, icon=icon, description=description, parties_count=parties, party_size=size,
                order=order, forum_subcategory=self.events_sub, ts_channels=channel,
                points_present=present, points_absent=absent, min_presence_minutes=30,
            )
            # Event и отряды создает сигнал при создании типа ивента.
            self.fill_parties(Event.objects.get(event_type=event_type))

            for days in {'ТВ': [-14, -7], 'КХ': [-10, -3], 'Мировой босс': [-5]}[name]:
                self.past_event(event_type, self.today + datetime.timedelta(days=days))
            self.upcoming_event(event_type, self.today + datetime.timedelta(days={'ТВ': 4, 'КХ': 2, 'Мировой босс': 1}[name]))

    def fill_parties(self, event):
        parties = list(event.parties.all())
        leaders = self.members[:len(parties)]
        others = [user for user in self.members if user not in leaders]
        for party, leader in zip(parties, leaders):
            party.leader = leader
            party.save(update_fields=['leader'])
            self.random.shuffle(others)
            for user in others[:self.random.randint(5, event.event_type.party_size - 2)]:
                if not PartyMember.objects.filter(party__event=event, user=user).exists():
                    PartyMember.objects.create(party=party, user=user)

    def notification(self, event_type, date):
        return EventNotification.objects.create(
            event_type=event_type, event_date=date, start_time=datetime.time(20, 0), duration_minutes=120,
            subject=f'{event_type.icon} {event_type.name} {date:%d.%m}',
            message=f'Сбор в TeamSpeak в канале «{event_type.ts_channels}» в 19:50.',
        )

    def answer(self, notification, user, weights):
        status = self.random.choices(['yes', 'maybe', 'no'], weights=weights)[0]
        comment = {'no': 'Работаю в этот день', 'maybe': 'Постараюсь успеть'}.get(status, '')
        EventAttendance.objects.create(notification=notification, user=user, status=status, comment=comment)
        return status

    def past_event(self, event_type, date):
        notification = self.notification(event_type, date)
        notification.sent_to_users.set(self.guild)
        for user in self.guild:
            status = self.answer(notification, user, [75, 15, 10])
            # Большинство «Приду» пришли, часть «Возможно» тоже — по ним бот TS насчитал минуты.
            if (status == 'yes' and self.random.random() < 0.85) or (status == 'maybe' and self.random.random() < 0.5):
                EventPresence.objects.create(notification=notification, user=user, minutes=self.random.randint(35, 120))
        # Итоги ивента подводятся так же, как после реального ивента: очки, штрафы, уведомления.
        finalize(notification.pk, now=notification.ends_at + datetime.timedelta(minutes=5))
        EventNotification.objects.filter(pk=notification.pk).update(sent_at=notification.starts_at - datetime.timedelta(days=2))

    def upcoming_event(self, event_type, date):
        notification = self.notification(event_type, date)
        send_event_notification(notification.id)
        # Часть игроков еще не ответила, гости отвечают сами.
        for user in self.members:
            if self.random.random() < 0.7:
                self.answer(notification, user, [70, 20, 10])

    # ===== Аукцион =====

    def lot(self, name, icon, price, step, days_left, description, started_days_ago):
        lot = AuctionLot.objects.create(
            name=name, icon_choice=icon, initial_price=price, min_step=step, description=description,
            start_date=self.now - datetime.timedelta(days=started_days_ago),
            end_date=self.now + datetime.timedelta(days=days_left),
        )
        return lot

    def bid(self, lot, user, amount):
        place_bid(DemoRequest(user), lot.id, amount)

    def create_auction(self):
        members = self.members
        stone = self.lot('Камень мироздания', 'stone_of_universe', 20, 5, 3, 'Выпал на КХ.', 2)
        for user, amount in [(members[3], 25), (members[7], 35), (members[2], 45)]:
            self.bid(stone, user, amount)
        wheel = self.lot('Колесо Судьбы', 'wheel_of_fate', 30, 5, 5, 'Выпало на КХ.', 1)
        self.bid(wheel, members[10], 35)
        self.lot('Набор рун 9 ур', 'rune_set_9', 40, 10, 6, 'Ставок пока нет — можно стать первым.', 0)

        # Завершенные лоты — через то же завершение, что делает администратор в админ-панели.
        opal = self.lot('Опал Лунной Кошки', 'opal', 15, 5, 1, 'Выпал на КХ.', 9)
        for user, amount in [(members[5], 20), (members[8], 30), (members[5], 40)]:
            self.bid(opal, user, amount)
        meteor = self.lot('Великий метеорит', 'great_meteorite', 10, 5, 1, 'Выпал с мирового босса.', 6)
        for user, amount in [(members[12], 15), (members[14], 25)]:
            self.bid(meteor, user, amount)
        for lot in (opal, meteor):
            lot.process_auction_end(ended_by_user=self.admin)
            AuctionLot.objects.filter(pk=lot.pk).update(
                end_date=self.now - datetime.timedelta(days=2), ended_at=self.now - datetime.timedelta(days=2))

    # ===== Заявки =====

    def application(self, user, status, plans, **extra):
        profile = user.profile
        return Application.objects.create(
            user=user, player_class=profile.get_player_class_display(), timezone=profile.timezone,
            age=profile.age(), development_plans=plans, status=status, **extra,
        )

    def create_reception(self):
        admin = self.admin
        voting_user, pending_user, rejected_user = self.applicants
        voting = self.application(
            voting_user, 'voting', 'Докачать оружие до +10, собрать сет на пробив, ходить на все ТВ.',
            previous_nicknames='Ночной_Лучник', other_guilds='Нет', guarantors='Искра, Сокол',
            reviewed_by=admin, approved_at=self.now - datetime.timedelta(days=1),
        )
        votes = [(self.members[5], 'for', 'Играли вместе, адекватный.'), (self.members[7], 'for', ''),
                 (self.members[2], 'against', 'Мало урона для ТВ, пусть подкачается.'), (self.members[9], 'abstain', ''),
                 (self.members[0], 'for', 'Нужны лучники.')]
        for voter, vote, comment in votes:
            ApplicationVote.objects.create(application=voting, voter=voter, vote=vote, comment=comment)

        self.application(pending_user, 'pending', 'Хочу в активную гильдию для ТВ и КХ.',
                         other_guilds='Обсидиан (ухожу)')
        self.application(rejected_user, 'rejected', 'Просто поиграть.', on_blacklist=True,
                         blacklist_details='В ЧС гильдии Багровый Рассвет за кидок на аукционе.',
                         admin_comment='Находится в ЧС союзной гильдии.', reviewed_by=admin)
        self.application(self.members[11], 'approved', 'Ходить на ТВ и КХ, качать жнеца.', reviewed_by=admin,
                         approved_at=self.now - datetime.timedelta(days=60))

    # ===== Кос-лист =====

    def create_koslist(self):
        for name in ['Багровый Рассвет', 'Обсидиан']:
            Guild.objects.create(name=name)
        for name, cls in [('Вор_Лута', 'sin'), ('Злыдень', 'var'), ('Кидала', 'mag'), ('Гриферша', 'luk')]:
            Player.objects.create(name=name, player_class=cls)
