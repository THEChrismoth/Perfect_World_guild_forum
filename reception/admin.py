from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.urls import reverse
from .models import Application, ApplicationVote
from notifications.utils import send_notification


class ApplicationVoteInline(admin.TabularInline):
    model = ApplicationVote
    extra = 0
    fields = ('voter', 'vote', 'comment', 'created_at')
    readonly_fields = ('voter', 'vote', 'comment', 'created_at')
    can_delete = False


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'player_class', 'status', 'created_at', 'votes_summary')
    list_filter = ('status', 'player_class', 'created_at')
    search_fields = ('user__username', 'real_name', 'previous_nicknames')
    readonly_fields = ('created_at', 'updated_at', 'approved_at', 'display_screenshots', 'votes_detail')
    inlines = [ApplicationVoteInline]

    fieldsets = (
        ('Основная информация', {'fields': ('user', 'player_class', 'status')}),
        ('Личные данные', {'fields': ('real_name', 'age', 'timezone')}),
        ('Игровая информация', {'fields': ('previous_nicknames', 'other_guilds', 'on_blacklist', 'blacklist_details')}),
        ('Планы и поручители', {'fields': ('development_plans', 'guarantors')}),
        ('Скриншоты', {'fields': ('display_screenshots', 'screenshot1', 'screenshot2', 'screenshot3', 'screenshot4',
                                  'screenshot5')}),
        ('Статус', {'fields': ('admin_comment', 'reviewed_by', 'created_at', 'updated_at', 'approved_at')}),
        ('Голосование', {'fields': ('votes_detail',), 'classes': ('wide',)}),
    )

    def display_screenshots(self, obj):
        screenshots = []
        for i in range(1, 6):
            screenshot = getattr(obj, f'screenshot{i}')
            if screenshot and screenshot.name and hasattr(screenshot, 'url') and screenshot.url:
                try:
                    img_html = format_html(
                        '<a href="{}" target="_blank"><img src="{}" style="max-height: 100px; margin: 5px;" /></a>',
                        screenshot.url, screenshot.url
                    )
                    screenshots.append(img_html)
                except Exception:
                    continue

        if screenshots:
            return mark_safe(''.join(screenshots))
        return mark_safe('<span style="color: #888;">Нет скриншотов</span>')

    display_screenshots.short_description = 'Скриншоты'

    def votes_detail(self, obj):
        votes = obj.votes.select_related('voter').all()
        if not votes:
            return mark_safe('<span style="color: #888;">Нет голосов</span>')

        stats = obj.get_vote_stats()
        html = f'<div style="background:#f8f9fa;padding:10px;margin-bottom:10px;border-radius:5px;"><h4 style="margin:0 0 10px 0;">Статистика:</h4>✅ За: {stats["for"]} | ❌ Против: {stats["against"]} | ⚪ Воздержались: {stats["abstain"]}</div>'
        html += '<table style="width:100%; border-collapse: collapse;">'
        html += '<tr style="background: #e9ecef;"><th style="padding: 8px; text-align: left;">Пользователь</th><th style="padding: 8px; text-align: left;">Голос</th><th style="padding: 8px; text-align: left;">Комментарий</th><th style="padding: 8px; text-align: left;">Дата</th><tr>'

        for vote in votes:
            color = '#28a745' if vote.vote == 'for' else '#dc3545' if vote.vote == 'against' else '#ffc107'
            vote_display = dict(ApplicationVote.VOTE_CHOICES).get(vote.vote, vote.vote)
            html += f'<tr style="border-bottom: 1px solid #dee2e6;"><td style="padding: 8px;">{vote.voter.username}</td><td style="padding: 8px; color:{color};"><strong>{vote_display}</strong></td><td style="padding: 8px;">{vote.comment or "-"}</td><td style="padding: 8px;">{vote.created_at.strftime("%d.%m.%Y %H:%M")}</td></tr>'

        html += '</table>'
        return mark_safe(html)

    votes_detail.short_description = 'Голоса (с именами)'

    def votes_summary(self, obj):
        stats = obj.get_vote_stats()
        return mark_safe(
            f'<span style="color: #28a745;">✅{stats["for"]}</span> <span style="color: #dc3545;">❌{stats["against"]}</span>')

    votes_summary.short_description = 'Голоса'

    def save_model(self, request, obj, form, change):
        old_status = None
        if change:
            try:
                old_status = Application.objects.get(id=obj.id).status
            except Application.DoesNotExist:
                pass

        if 'status' in form.changed_data:
            # Допуск до голосования
            if obj.status == 'voting' and old_status != 'voting':
                obj.approve_by_admin(request.user)
                send_notification(
                    user=obj.user,
                    title='📝 Заявка допущена до голосования',
                    message=f'Ваша заявка прошла предварительную проверку и допущена до голосования членов гильдии.',
                    notification_type='application',
                    link=reverse('reception:application_detail', args=[obj.id])
                )
            # Отклонение заявки
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
            # Одобрение заявки (финальное) - группа выдается вручную, только уведомление
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
        """Допустить до голосования"""
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
        """Отклонить заявки"""
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
        """Финальное одобрение заявок"""
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
class ApplicationVoteAdmin(admin.ModelAdmin):
    list_display = ('application', 'voter', 'vote', 'created_at')
    list_filter = ('vote', 'created_at')
    search_fields = ('voter__username', 'application__user__username')
    readonly_fields = ('created_at',)