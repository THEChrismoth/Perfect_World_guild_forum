from django import forms
from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.urls import reverse

from core.admin_mixins import NoRelatedPopupsMixin
from .models import Application, ApplicationVote
from notifications.utils import send_notification

VOTE_CLASSES = {'for': 'ga-text-ok', 'against': 'ga-text-bad', 'abstain': 'ga-text-warn'}


class ApplicationVoteInline(NoRelatedPopupsMixin, admin.TabularInline):
    model = ApplicationVote
    extra = 0
    fields = ('voter', 'vote', 'comment', 'created_at')
    readonly_fields = ('voter', 'vote', 'comment', 'created_at')
    can_delete = False


class ApplicationForm(forms.ModelForm):
    class Meta:
        model = Application
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        # Причина отказа уходит кандидату в уведомлении — без неё он не поймёт, что исправить.
        if cleaned_data.get('status') == 'rejected' and self.instance.status != 'rejected' \
                and not (cleaned_data.get('admin_comment') or '').strip():
            self.add_error('admin_comment', 'Напишите причину отказа — кандидат увидит её в уведомлении')
        return cleaned_data


@admin.register(Application)
class ApplicationAdmin(NoRelatedPopupsMixin, admin.ModelAdmin):
    form = ApplicationForm
    list_display = ('id', 'user', 'player_class', 'status', 'created_at', 'votes_summary')
    list_filter = ('status', 'player_class', 'created_at')
    search_fields = ('user__username', 'real_name', 'previous_nicknames')
    readonly_fields = ('reviewed_by', 'created_at', 'updated_at', 'approved_at', 'display_screenshots', 'votes_detail')
    inlines = [ApplicationVoteInline]

    fieldsets = (
        ('Решение', {
            'fields': ('status', 'admin_comment', 'reviewed_by'),
            'description': '«Голосование» — заявка прошла проверку, члены гильдии голосуют на сайте. '
                           '«Одобрена» — финальное решение, группу «Член гильдии» выдайте в разделе «Пользователи». '
                           '«Отклонена» — укажите причину в комментарии. Кандидат получает уведомление о каждом решении.',
        }),
        ('Кандидат', {'fields': ('user', 'player_class', 'real_name', 'age', 'timezone')}),
        ('Игровой опыт', {'fields': ('previous_nicknames', 'other_guilds', 'on_blacklist', 'blacklist_details')}),
        ('Планы и поручители', {'fields': ('development_plans', 'guarantors')}),
        ('Скриншоты', {'fields': ('display_screenshots', 'screenshot1', 'screenshot2', 'screenshot3', 'screenshot4',
                                  'screenshot5')}),
        ('Голосование', {'fields': ('votes_detail',), 'classes': ('wide',)}),
        ('Даты', {'fields': ('created_at', 'updated_at', 'approved_at'), 'classes': ('collapse',)}),
    )

    def display_screenshots(self, obj):
        urls = []
        for i in range(1, 6):
            screenshot = getattr(obj, f'screenshot{i}')
            if screenshot and screenshot.name:
                try:
                    urls.append((screenshot.url, screenshot.url))
                except ValueError:
                    continue
        if not urls:
            return format_html('<span class="ga-text-muted">{}</span>', 'Нет скриншотов')
        return format_html('<div class="ga-shots">{}</div>', format_html_join(
            '', '<a href="{}" target="_blank" rel="noopener"><img src="{}" alt=""></a>', urls))

    display_screenshots.short_description = 'Скриншоты'

    def votes_detail(self, obj):
        votes = obj.votes.select_related('voter').all()
        if not votes:
            return format_html('<span class="ga-text-muted">{}</span>', 'Нет голосов')

        stats = obj.get_vote_stats()
        header = format_html(
            '<div class="ga-votes-summary"><span class="ga-text-ok">За: {}</span>'
            '<span class="ga-text-bad">Против: {}</span><span class="ga-text-warn">Воздержались: {}</span></div>',
            stats['for'], stats['against'], stats['abstain']
        )
        # format_html_join экранирует имя и комментарий — их пишут пользователи.
        rows = format_html_join(
            '',
            '<tr><td>{}</td><td class="{}"><strong>{}</strong></td><td>{}</td><td>{}</td></tr>',
            (
                (
                    vote.voter.username,
                    VOTE_CLASSES.get(vote.vote, ''),
                    vote.get_vote_display(),
                    vote.comment or '—',
                    timezone.localtime(vote.created_at).strftime('%d.%m.%Y %H:%M'),
                )
                for vote in votes
            )
        )
        return format_html(
            '{}<table class="ga-votes"><thead><tr><th>Пользователь</th><th>Голос</th><th>Комментарий</th>'
            '<th>Дата</th></tr></thead><tbody>{}</tbody></table>',
            header, rows
        )

    votes_detail.short_description = 'Голоса (с именами)'

    def votes_summary(self, obj):
        stats = obj.get_vote_stats()
        return format_html('<span class="ga-text-ok">За {}</span> · <span class="ga-text-bad">против {}</span>',
                           stats['for'], stats['against'])

    votes_summary.short_description = 'Голоса'

    def save_model(self, request, obj, form, change):
        old_status = None
        if change:
            try:
                old_status = Application.objects.get(id=obj.id).status
            except Application.DoesNotExist:
                pass

        if 'status' in form.changed_data:
            # Допуск до голосования.
            if obj.status == 'voting' and old_status != 'voting':
                obj.approve_by_admin(request.user)
                send_notification(
                    user=obj.user,
                    title='📝 Заявка допущена до голосования',
                    message=f'Ваша заявка прошла предварительную проверку и допущена до голосования членов гильдии.',
                    notification_type='application',
                    link=reverse('reception:application_detail', args=[obj.id])
                )
            # Отклонение заявки.
            elif obj.status == 'rejected' and old_status != 'rejected':
                obj.reject_by_admin(request.user, obj.admin_comment)
                reason = obj.admin_comment if obj.admin_comment else 'Не указана'
                send_notification(
                    user=obj.user,
                    title='❌ Заявка отклонена',
                    message=f'Ваша заявка была отклонена. Причина: {reason}',
                    notification_type='error',
                    link=reverse('reception:my_applications')
                )
            # Одобрение заявки (финальное) — группа выдается вручную, только уведомление.
            elif obj.status == 'approved' and old_status != 'approved':
                obj.status = 'approved'
                obj.save()
                send_notification(
                    user=obj.user,
                    title='🎉 Заявка одобрена!',
                    message=f'Поздравляем! Ваша заявка одобрена! Теперь вы можете вступить в гильдию.',
                    notification_type='success',
                    link=reverse('reception:my_applications')
                )
                return  # Выходим, чтобы не вызывать super().save_model дважды

        super().save_model(request, obj, form, change)

    actions = ['approve_applications', 'reject_applications', 'final_approve_applications']

    def approve_applications(self, request, queryset):
        """Допускает до голосования."""
        count = 0
        for app in queryset.filter(status='pending'):
            app.approve_by_admin(request.user)
            send_notification(
                user=app.user,
                title='📝 Заявка допущена до голосования',
                message=f'Ваша заявка прошла предварительную проверку и допущена до голосования.',
                notification_type='application',
                link=reverse('reception:application_detail', args=[app.id])
            )
            count += 1
        self.message_user(request, f'Допущено до голосования {count} заявок')
    approve_applications.short_description = 'Допустить до голосования'

    def reject_applications(self, request, queryset):
        """Отклоняет заявки."""
        count = 0
        for app in queryset.filter(status='pending'):
            app.reject_by_admin(request.user, 'Отклонено администратором')
            send_notification(
                user=app.user,
                title='❌ Заявка отклонена',
                message=f'Ваша заявка была отклонена администратором.',
                notification_type='error',
                link=reverse('reception:my_applications')
            )
            count += 1
        self.message_user(request, f'Отклонено {count} заявок')
    reject_applications.short_description = 'Отклонить'

    def final_approve_applications(self, request, queryset):
        """Финальное одобрение заявок."""
        count = 0
        for app in queryset.filter(status='voting'):
            app.status = 'approved'
            app.save()
            send_notification(
                user=app.user,
                title='🎉 Заявка одобрена!',
                message=f'Поздравляем! Ваша заявка одобрена. Свяжитесь с администратором для вступления в гильдию.',
                notification_type='success',
                link=reverse('reception:my_applications')
            )
            count += 1
        self.message_user(request, f'Одобрено {count} заявок, уведомления отправлены')
    final_approve_applications.short_description = 'Одобрить заявки (отправить уведомление)'


@admin.register(ApplicationVote)
class ApplicationVoteAdmin(NoRelatedPopupsMixin, admin.ModelAdmin):
    list_display = ('application', 'voter', 'vote', 'created_at')
    list_filter = ('vote', 'created_at')
    search_fields = ('voter__username', 'application__user__username')
    readonly_fields = ('created_at',)