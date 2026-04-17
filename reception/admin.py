from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from .models import Application, ApplicationVote, ApplicationNotification


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
        ('Скриншоты', {'fields': ('display_screenshots', 'screenshot1', 'screenshot2', 'screenshot3', 'screenshot4', 'screenshot5')}),
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
        html += '<tr style="background: #e9ecef;"><th style="padding: 8px; text-align: left;">Пользователь</th><th style="padding: 8px; text-align: left;">Голос</th><th style="padding: 8px; text-align: left;">Комментарий</th><th style="padding: 8px; text-align: left;">Дата</th></tr>'
        
        for vote in votes:
            color = '#28a745' if vote.vote == 'for' else '#dc3545' if vote.vote == 'against' else '#ffc107'
            vote_display = dict(ApplicationVote.VOTE_CHOICES).get(vote.vote, vote.vote)
            html += f'<tr style="border-bottom: 1px solid #dee2e6;"><td style="padding: 8px;">{vote.voter.username}</td><td style="padding: 8px; color:{color};"><strong>{vote_display}</strong></td><td style="padding: 8px;">{vote.comment or "-"}</td><td style="padding: 8px;">{vote.created_at.strftime("%d.%m.%Y %H:%M")}</td></tr>'
        
        html += '</table>'
        return mark_safe(html)
    votes_detail.short_description = 'Голоса (с именами)'
    
    def votes_summary(self, obj):
        stats = obj.get_vote_stats()
        return mark_safe(f'<span style="color: #28a745;">✅{stats["for"]}</span> <span style="color: #dc3545;">❌{stats["against"]}</span>')
    votes_summary.short_description = 'Голоса'
    
    def save_model(self, request, obj, form, change):
        if 'status' in form.changed_data:
            if obj.status == 'voting':
                obj.approve_by_admin(request.user)
                ApplicationNotification.objects.create(
                    user=obj.user,
                    application=obj,
                    message=f'Ваша заявка допущена до голосования!'
                )
            elif obj.status == 'rejected':
                obj.reject_by_admin(request.user, obj.admin_comment)
                ApplicationNotification.objects.create(
                    user=obj.user,
                    application=obj,
                    message=f'Ваша заявка отклонена. Причина: {obj.admin_comment if obj.admin_comment else "Не указана"}'
                )
        super().save_model(request, obj, form, change)
    
    actions = ['approve_applications', 'reject_applications', 'final_approve_applications']
    
    def approve_applications(self, request, queryset):
        count = 0
        for app in queryset.filter(status='pending'):
            app.approve_by_admin(request.user)
            ApplicationNotification.objects.create(
                user=app.user,
                application=app,
                message=f'Ваша заявка допущена до голосования!'
            )
            count += 1
        self.message_user(request, f'Допущено до голосования {count} заявок')
    approve_applications.short_description = 'Допустить до голосования'
    
    def reject_applications(self, request, queryset):
        count = 0
        for app in queryset.filter(status='pending'):
            app.reject_by_admin(request.user, 'Отклонено администратором')
            ApplicationNotification.objects.create(
                user=app.user,
                application=app,
                message=f'Ваша заявка отклонена администратором.'
            )
            count += 1
        self.message_user(request, f'Отклонено {count} заявок')
    reject_applications.short_description = 'Отклонить'
    
    def final_approve_applications(self, request, queryset):
        count = 0
        for app in queryset.filter(status='voting'):
            app.final_approve()
            ApplicationNotification.objects.create(
                user=app.user,
                application=app,
                message=f'Поздравляем! Ваша заявка одобрена! Вы добавлены в группу "Член гильдии".'
            )
            count += 1
        self.message_user(request, f'Одобрено и выдана группа "Член гильдии" {count} заявкам')
    final_approve_applications.short_description = 'Финально одобрить (выдать группу)'


@admin.register(ApplicationVote)
class ApplicationVoteAdmin(admin.ModelAdmin):
    list_display = ('application', 'voter', 'vote', 'created_at')
    list_filter = ('vote', 'created_at')
    search_fields = ('voter__username', 'application__user__username')
    readonly_fields = ('created_at',)


@admin.register(ApplicationNotification)
class ApplicationNotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'application', 'message', 'is_read', 'created_at')
    list_filter = ('is_read', 'created_at')
    search_fields = ('user__username', 'message')
