from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.views.decorators.http import require_POST

from core.admin_mixins import NoRelatedPopupsMixin
from core.roles import GUILD_GROUP
from . import services
from .models import Application


@admin.register(Application)
class ApplicationAdmin(NoRelatedPopupsMixin, admin.ModelAdmin):
    """Заявки создают кандидаты на сайте. Здесь их только смотрят и принимают решение:
    вынести на голосование, одобрить или отклонить — кнопками на странице заявки."""

    list_display = ('user', 'player_class', 'status', 'created_at', 'votes_summary')
    list_filter = ('status', 'created_at')
    search_fields = ('user__username', 'development_plans')
    actions = ['send_to_voting_action']

    def has_add_permission(self, request):
        return False

    @admin.display(description='Голоса')
    def votes_summary(self, obj):
        stats = obj.get_vote_stats()
        return format_html('<span class="ga-text-ok">За {}</span> · <span class="ga-text-bad">против {}</span>',
                           stats['for'], stats['against'])

    @admin.action(description='Вынести на голосование')
    def send_to_voting_action(self, request, queryset):
        applications = [app for app in queryset if services.can_decide(app, 'voting')]
        for app in applications:
            services.send_to_voting(app, request.user)
        self.message_user(request, f'Вынесено на голосование: {len(applications)}')

    def changelist_view(self, request, extra_context=None):
        return super().changelist_view(request, {'title': 'Заявки в гильдию', **(extra_context or {})})

    def get_urls(self):
        return [
            path('<int:object_id>/decision/', self.admin_site.admin_view(require_POST(self.decision_view)),
                 name='reception_application_decision'),
        ] + super().get_urls()

    def change_view(self, request, object_id, form_url='', extra_context=None):
        """Вместо формы — заявка целиком, голоса с комментариями и кнопки решения."""
        application = get_object_or_404(Application.objects.select_related('user__profile', 'reviewed_by'),
                                        pk=object_id)
        if not self.has_view_or_change_permission(request, application):
            raise PermissionDenied
        context = {
            **self.admin_site.each_context(request),
            'title': f'Заявка · {application.user.username}',
            'opts': self.model._meta,
            'original': application,
            'application': application,
            'profile': application.user.profile,
            'stats': application.get_vote_stats(),
            'items': services.discussion_items(application),
            'can_change': self.has_change_permission(request, application),
            'can_delete': self.has_delete_permission(request, application),
            'can_vote_out': services.can_decide(application, 'voting'),
            'can_approve': services.can_decide(application, 'approve'),
            'can_reject': services.can_decide(application, 'reject'),
            'guild_group': GUILD_GROUP,
        }
        return TemplateResponse(request, 'admin/reception/application/detail.html', context)

    def decision_view(self, request, object_id):
        application = get_object_or_404(Application, pk=object_id)
        if not self.has_change_permission(request, application):
            raise PermissionDenied
        decision = request.POST.get('decision')
        back = HttpResponseRedirect(reverse('admin:reception_application_change', args=[application.pk]))

        if not services.can_decide(application, decision):
            self.message_user(request, 'Это решение для заявки в таком статусе недоступно', level=messages.ERROR)
            return back

        if decision == 'voting':
            services.send_to_voting(application, request.user)
            self.message_user(request, 'Заявка вынесена на голосование, кандидат получил уведомление')
        elif decision == 'approve':
            services.approve(application, request.user, add_to_guild=bool(request.POST.get('add_to_guild')))
            self.message_user(request, 'Заявка одобрена, кандидат получил уведомление')
        else:
            reason = request.POST.get('reason', '').strip()
            if not reason:
                self.message_user(request, 'Напишите причину отказа — кандидат увидит её в уведомлении',
                                  level=messages.ERROR)
                return back
            services.reject(application, request.user, reason)
            self.message_user(request, 'Заявка отклонена, кандидат получил уведомление с причиной')
        return back
