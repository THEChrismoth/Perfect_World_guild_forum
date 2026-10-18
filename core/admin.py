from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse
from .models import SiteSettings


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    fields = ('site_name', 'favicon')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        # Запись всего одна — сразу открываем ее редактирование
        obj = SiteSettings.load()
        return redirect(reverse('admin:core_sitesettings_change', args=[obj.pk]))
