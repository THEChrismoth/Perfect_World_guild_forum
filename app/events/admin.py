from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from core.admin_mixins import NoRelatedPopupsMixin, related_hint
from .forms import PartyRosterForm
from .models import EventType, Event, Party, PartyMember, EventNotification, EventAttendance
from .services import save_party_roster
from .utils import send_event_notification


class EventTypeForm(forms.ModelForm):
    roster_notes = forms.CharField(label='Примечания к составу', required=False,
                                  widget=forms.Textarea(attrs={'rows': 2}))

    class Meta:
        model = EventType
        fields = '__all__'
        widgets = {'description': forms.Textarea(attrs={'rows': 3}),
                   'ts_channels': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            roster = Event.objects.filter(event_type=self.instance).first()
            self.fields['roster_notes'].initial = roster.notes if roster else ''
        self.fields['name'].label = 'Название ивента'
        self.fields['parties_count'].help_text = 'Постоянные отряды создаются автоматически. Занятые сначала нужно освободить.'
        self.fields['party_size'].help_text = 'Общее число игроков в одном отряде, включая лидера.'
        self.fields['ts_channels'].help_text = 'По одному пути на строку. Например: Гильдия / МТВ. Пусто — без автоматического учёта.'
        self.fields['points_present'].label = 'Очки за участие'
        self.fields['points_absent'].label = 'Штраф за пропуск'
        self.fields['min_presence_minutes'].label = 'Минут для зачёта'
        self.fields['forum_subcategory'].help_text = related_hint(
            'Раздел для обсуждения ивента.', 'admin:forum_subcategory_changelist', 'Разделы форума')

    def clean(self):
        data = super().clean()
        for field in ('parties_count', 'party_size', 'min_presence_minutes'):
            if data.get(field) == 0:
                self.add_error(field, 'Должно быть хотя бы 1.')
        if self.instance.pk:
            roster = Event.objects.filter(event_type=self.instance).prefetch_related('parties__members').first()
            if roster:
                for party in roster.parties.all():
                    if party.members_count > (data.get('party_size') or 0):
                        self.add_error('party_size', 'Размер меньше существующего состава отряда.')
                        break
                if roster.parties.filter(number__gt=data.get('parties_count') or 0).filter(
                        Q(leader__isnull=False) | Q(members__isnull=False)).exists():
                    self.add_error('parties_count', 'Сначала освободите удаляемые отряды.')
        return data


class EventsAdminMixin:
    change_list_template = 'admin/events/change_list.html'

    class Media:
        css = {'all': ('admin/css/events.css',)}

    def changelist_view(self, request, extra_context=None):
        return super().changelist_view(request, extra_context={
            **(extra_context or {}), 'events_section': self.model._meta.model_name,
            'title': 'Типы ивентов' if self.model is EventType else 'Даты проведения'})


@admin.register(EventType)
class EventTypeAdmin(EventsAdminMixin, NoRelatedPopupsMixin, admin.ModelAdmin):
    form = EventTypeForm
    change_form_template = 'admin/events/eventtype/change_form.html'
    list_display = ['name', 'roster_size', 'tracking_mode', 'is_active', 'manage_roster', 'dates_link']
    list_display_links = ['name']
    list_filter = ['is_active']
    search_fields = ['name', 'description']
    ordering = ['order', 'name']
    fieldsets = (
        ('Основное', {'fields': ('name', 'description', 'is_active')}),
        ('Постоянные отряды', {
            'fields': (('parties_count', 'party_size'), 'roster_notes'),
            'description': 'Состав сохраняется между датами проведения. Игроки назначаются на вкладке «Отряды».',
        }),
        ('Посещение и очки', {
            'fields': ('ts_channels', 'min_presence_minutes', ('points_present', 'points_absent'), 'penalty_scope'),
            'description': 'TeamSpeak подтверждает фактическое присутствие. Очки необязательны: оставьте нули для учёта без наград и штрафов.',
        }),
        ('Дополнительно', {'fields': ('forum_subcategory', 'icon', 'order'), 'classes': ('collapse',)}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('roster__parties__members')

    def get_urls(self):
        return [path('<int:object_id>/roster/', self.admin_site.admin_view(self.roster_view),
                     name='events_eventtype_roster')] + super().get_urls()

    @admin.display(description='Отряды / места')
    def roster_size(self, obj):
        roster = getattr(obj, 'roster', None)
        filled = sum(party.members_count for party in roster.parties.all()) if roster else 0
        return f'{obj.parties_count} отр. · {filled} / {obj.total_slots} мест'

    @admin.display(description='Посещение')
    def tracking_mode(self, obj):
        return f'TeamSpeak · от {obj.min_presence_minutes} мин.' if obj.ts_channels.strip() else 'Без автоматического учёта'

    @admin.display(description='Состав')
    def manage_roster(self, obj):
        return format_html('<a class="ga-btn-secondary" href="{}">Отряды</a>',
                           reverse('admin:events_eventtype_roster', args=[obj.pk]))

    @admin.display(description='Проведения')
    def dates_link(self, obj):
        return format_html('<a href="{}?event_type__id__exact={}">Даты и приглашения →</a>',
                           reverse('admin:events_eventnotification_changelist'), obj.pk)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        Event.objects.filter(event_type=obj).update(notes=form.cleaned_data['roster_notes'])

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        obj = self.get_object(request, object_id) if object_id else None
        return super().changeform_view(request, object_id, form_url, {
            **(extra_context or {}), 'events_section': 'eventtype', 'event_type': obj,
            'roster_summary': self.roster_size(obj) if obj else None,
            'title': f'Настройки · {obj.name}' if obj else 'Создать тип ивента',
        })

    def roster_view(self, request, object_id):
        """Показывает постоянные отряды внутри общей темы админ-панели."""
        obj = get_object_or_404(self.get_queryset(request), pk=object_id)
        if not self.has_view_or_change_permission(request, obj) and not request.user.has_perm('events.change_party'):
            raise PermissionDenied
        roster = Event.objects.filter(event_type=obj).first()
        parties = roster.parties.select_related('leader').prefetch_related('members__user') if roster else []
        return TemplateResponse(request, 'admin/events/roster.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta, 'event_type': obj,
            'title': f'{obj.name} · постоянные отряды', 'parties': parties,
            'can_edit_parties': request.user.has_perm('events.change_party'),
            'media': self.media,
        })


@admin.register(Party)
class PartyAdmin(EventsAdminMixin, NoRelatedPopupsMixin, admin.ModelAdmin):
    def get_model_perms(self, request):
        return {}

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        """Редактирует отряд через общий сервис проверки состава."""
        party = get_object_or_404(Party.objects.select_related('event__event_type'), pk=object_id)
        if not self.has_view_or_change_permission(request, party):
            raise PermissionDenied
        can_edit = self.has_change_permission(request, party)
        if request.method == 'POST' and not can_edit:
            raise PermissionDenied
        form = PartyRosterForm(request.POST if request.method == 'POST' else None, party=party)
        if request.method == 'POST' and form.is_valid():
            try:
                save_party_roster(party, form.cleaned_data['leader'], form.cleaned_data['members'])
            except ValidationError as error:
                form.add_error(None, error)
            else:
                self.message_user(request, 'Постоянный отряд сохранён')
                return redirect('admin:events_eventtype_roster', object_id=party.event.event_type_id)
        if not can_edit:
            for field in form.fields.values():
                field.disabled = True
        return TemplateResponse(request, 'admin/events/party_form.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta, 'party': party,
            'event_type': party.event.event_type, 'form': form, 'can_edit': can_edit,
            'title': f'{party.event.event_type.name} · отряд {party.number}', 'media': self.media,
        })


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    def get_model_perms(self, request):
        return {}

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        obj = get_object_or_404(Event, pk=object_id)
        if not self.has_view_or_change_permission(request, obj):
            raise PermissionDenied
        return redirect('admin:events_eventtype_change', obj.event_type_id)


@admin.register(PartyMember)
class PartyMemberAdmin(admin.ModelAdmin):
    def get_model_perms(self, request):
        return {}

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class EventNotificationForm(forms.ModelForm):
    class Meta:
        model = EventNotification
        fields = '__all__'
        widgets = {
            'event_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'start_time': forms.TimeInput(attrs={'type': 'time'}, format='%H:%M'),
            'message': forms.Textarea(attrs={'rows': 3}),
            'recipient_groups': forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        labels = {'event_type': 'Тип ивента', 'event_date': 'Дата проведения',
                  'start_time': 'Начало по Москве', 'duration_minutes': 'Длительность, минут'}
        for name, label in labels.items():
            if name in self.fields:
                self.fields[name].label = label
        if 'start_time' in self.fields:
            self.fields['start_time'].required = True
        if 'subject' in self.fields:
            self.fields['subject'].help_text = 'Можно оставить пустым — название и дата подставятся автоматически.'
        if 'recipient_groups' in self.fields:
            self.fields['recipient_groups'].help_text = 'Ничего не выбрано — все активные члены гильдии. Выберите группы для отдельной рассылки.'

    def clean(self):
        data = super().clean()
        if not self.instance.sent_at and data.get('event_date') and data['event_date'] < timezone.localdate():
            self.add_error('event_date', 'Эта дата уже прошла.')
        if data.get('duration_minutes') is not None and data['duration_minutes'] < 1:
            self.add_error('duration_minutes', 'Длительность должна быть больше нуля.')
        return data


class InvitationStateFilter(admin.SimpleListFilter):
    title = 'Рассылка'
    parameter_name = 'invitation_state'

    def lookups(self, request, model_admin):
        return [('draft', 'Черновики'), ('sent', 'Отправленные')]

    def queryset(self, request, queryset):
        if self.value() in ('draft', 'sent'):
            return queryset.filter(sent_at__isnull=self.value() == 'draft')
        return queryset


@admin.register(EventNotification)
class EventNotificationAdmin(EventsAdminMixin, NoRelatedPopupsMixin, admin.ModelAdmin):
    form = EventNotificationForm
    change_form_template = 'admin/events/eventnotification/change_form.html'
    list_display = ['date_label', 'type_label', 'send_status', 'recipients_count', 'responses_count', 'report_link']
    list_display_links = ['date_label']
    list_filter = [InvitationStateFilter, 'event_type', 'event_date']
    search_fields = ['subject', 'message', 'event_type__name']
    ordering = ['-event_date', '-start_time']
    list_select_related = ['event_type']
    actions = None
    readonly_fields = ['sent_at', 'responses_count', 'recipients_count', 'points_processed_at', 'recipient_summary']
    fieldsets = (
        ('Дата и время', {
            'fields': ('event_type', ('event_date', 'start_time'), 'duration_minutes'),
            'description': 'Сначала назначьте дату. После отправки время и получатели фиксируются для учёта явки.',
        }),
        ('Приглашение игрокам', {'fields': ('subject', 'message')}),
        ('Кому отправить', {'fields': ('recipient_groups',)}),
        ('Результаты', {'fields': (('sent_at', 'points_processed_at'),), 'classes': ('collapse',)}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('event_type').prefetch_related('recipient_groups').annotate(
            _recipients=Count('sent_to_users', distinct=True), _responses=Count('attendances', distinct=True))

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.sent_at:
            return [*self.readonly_fields, 'event_type', 'event_date', 'start_time', 'duration_minutes', 'recipient_groups']
        return self.readonly_fields

    def get_fieldsets(self, request, obj=None):
        if not obj or not obj.sent_at:
            return self.fieldsets
        return tuple((title, {**options, 'fields': ('recipient_summary',)})
                     if title == 'Кому отправить' else (title, options)
                     for title, options in self.fieldsets)

    @admin.display(description='Получатели')
    def recipient_summary(self, obj):
        names = [group.name for group in obj.recipient_groups.all()]
        return ', '.join(names) if names else 'Все активные члены гильдии на момент отправки'

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        if not initial.get('event_type') and request.GET.get('event_type__id__exact'):
            initial['event_type'] = request.GET['event_type__id__exact']
        return initial

    @admin.display(description='Дата / начало', ordering='event_date')
    def date_label(self, obj):
        return format_html('{} · {}', obj.event_date.strftime('%d.%m.%Y'),
                           obj.start_time.strftime('%H:%M') if obj.start_time else 'без времени')

    @admin.display(description='Тип ивента', ordering='event_type__name')
    def type_label(self, obj):
        return obj.event_type.name

    @admin.display(description='Приглашение')
    def send_status(self, obj):
        if not obj.sent_at:
            return format_html('<span class="ga-pill ga-pill-pending">{}</span>', 'Черновик')
        return format_html('<span class="ga-pill ga-pill-approved">{}</span>',
                           'Приём ответов' if obj.response_open else 'Завершён')

    @admin.display(description='Приглашено')
    def recipients_count(self, obj):
        return obj._recipients

    @admin.display(description='Ответили')
    def responses_count(self, obj):
        return obj._responses

    @admin.display(description='Явка')
    def report_link(self, obj):
        return format_html('<a href="{}">Ответы и явка →</a>', reverse('events:vote_results', args=[obj.pk]))

    def _send(self, request, obj):
        """Отправляет сохранённый черновик и сообщает действительный результат."""
        result = send_event_notification(obj.pk)
        if result:
            self.message_user(request, f'Приглашение отправлено: {result} игроков.')
        else:
            self.message_user(request, 'Приглашение не отправлено: оно уже отправлялось, нет получателей или дата завершена.', level=messages.WARNING)
        if self.has_view_or_change_permission(request, obj):
            return redirect('admin:events_eventnotification_change', obj.pk)
        return redirect('admin:index')

    def response_add(self, request, obj, post_url_continue=None):
        if '_send_notification' in request.POST:
            return self._send(request, obj)
        return super().response_add(request, obj, post_url_continue)

    def response_change(self, request, obj):
        if '_send_notification' in request.POST:
            return self._send(request, obj)
        return super().response_change(request, obj)

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        obj = self.get_object(request, object_id) if object_id else None
        can_save = self.has_change_permission(request, obj) if obj else self.has_add_permission(request)
        return super().changeform_view(request, object_id, form_url, {
            **(extra_context or {}), 'events_section': 'eventnotification',
            'show_send_button': can_save and (not obj or not obj.sent_at),
            'date_object': obj, 'invited_total': obj._recipients if obj else 0,
            'responses_total': obj._responses if obj else 0,
            'title': f'{obj.event_type.name} · {obj.event_date:%d.%m.%Y}' if obj else 'Назначить дату ивента',
        })


@admin.register(EventAttendance)
class EventAttendanceAdmin(NoRelatedPopupsMixin, admin.ModelAdmin):
    list_display = ['user', 'notification', 'status', 'updated_at']
    list_filter = ['status', 'notification__event_type', 'notification__event_date']
    search_fields = ['user__username', 'comment']
    readonly_fields = ['created_at', 'updated_at']

    def get_model_perms(self, request):
        return {}
