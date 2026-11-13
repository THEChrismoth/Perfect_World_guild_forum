from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.urls import path
from django.db import models

from core.admin_mixins import NoRelatedPopupsMixin
from .models import GearSet, Profile
from . import admin_views
from .forms import GearSetForm


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    fieldsets = (
        ('Основная информация', {
            'fields': ('avatar', 'ts3_id', 'player_class', 'main_set')
        }),
        ('Очки активности', {
            'fields': ('activity_points', 'spent_points', 'earned_points'),
            'description': 'Меняются в «Таблице активности» — так правка попадёт в историю очков игрока',
        }),
    )
    # Правка здесь не попала бы в «Движение моих очков» у игрока — только просмотр.
    readonly_fields = ('activity_points', 'spent_points', 'earned_points')
    extra = 0
    max_num = 1
    min_num = 1


class GearSetInline(admin.StackedInline):
    """Два сета брони игрока — ПА и ПЗ; их ровно два, добавлять и удалять нельзя."""
    model = GearSet
    form = GearSetForm
    can_delete = False
    extra = 0
    max_num = 2
    fields = ('kind', ('hp', 'bd', 'bu'), ('pa', 'attack', 'pierce'),
              ('pz', 'physical_defense', 'magic_defense'))
    readonly_fields = ('kind',)

    class Media:
        js = ('profiles/js/damage_stats.js',)

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)
        selected = request.POST.get('profile-0-player_class', obj.profile.player_class if obj else None)

        class ClassGearSetFormSet(formset):
            def get_form_kwargs(self, index):
                return {**super().get_form_kwargs(index), 'player_class': selected}

        return ClassGearSetFormSet

    def has_add_permission(self, request, obj=None):
        return False


class UserAdmin(NoRelatedPopupsMixin, BaseUserAdmin):
    inlines = [ProfileInline, GearSetInline]
    # Дата последнего входа и регистрации заполняются сами — править их вручную незачем.
    fieldsets = tuple(fieldset for fieldset in BaseUserAdmin.fieldsets
                      if 'last_login' not in fieldset[1]['fields'])

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('activity-management/', admin_views.activity_management, name='activity_management'),
            path('activity/update/', admin_views.update_activity_points, name='update_activity_points'),
        ]
        return custom_urls + urls

# Создаем кастомный ModelAdmin для отображения в меню.
class ActivityManagementAdmin(admin.ModelAdmin):
    """Фейковый ModelAdmin для отображения пункта в меню."""

    def has_module_permission(self, request):
        return request.user.is_staff

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return request.user.is_staff

    def changelist_view(self, request, extra_context=None):
        """Перенаправляет на страницу управления активностью."""
        from django.shortcuts import redirect
        return redirect('admin:activity_management')


# Регистрируем User с кастомным админом.
admin.site.unregister(User)
admin.site.register(User, UserAdmin)

# Регистрируем фейковую модель для отображения в меню.
from django.contrib.admin import SimpleListFilter


class DummyModel(models.Model):
    class Meta:
        managed = False
        verbose_name = 'Таблица активности'
        verbose_name_plural = 'Таблица активности'
        # Модель должна принадлежать нашему приложению: с app_label='auth' makemigrations
        # создавал миграцию внутри установленного Django (.venv), и она не попадала в репозиторий.
        app_label = 'profiles'


# Регистрируем фейковую модель.
admin.site.register(DummyModel, ActivityManagementAdmin)
