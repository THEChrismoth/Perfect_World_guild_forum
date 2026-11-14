from django.contrib import admin
from django.utils.html import format_html

from .models import Skirmish


@admin.register(Skirmish)
class SkirmishAdmin(admin.ModelAdmin):
    list_display = ('title', 'started_at', 'ended_at', 'open_on_site')
    readonly_fields = ('title', 'organizer', 'started_at', 'ended_at', 'reviewed_at', 'reviewed_by',
                       'ts_channel', 'include_children', 'min_minutes', 'last_report_at', 'open_on_site')
    fields = readonly_fields

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description='Управление сбором')
    def open_on_site(self, obj):
        return format_html('<a href="{}">Открыть замес →</a>', obj.get_absolute_url())
