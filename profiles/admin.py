from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.urls import path
from django.db import models
from .models import Profile
from . import admin_views


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    fieldsets = (
        ('Основная информация', {
            'fields': ('avatar', 'ts3_id', 'birth_date', 'city', 'player_class')
        }),
        ('Характеристики', {
            'fields': ('hp', 'mp', 'bd')
        }),
        ('атака', {
            'fields': ('pa', 'fa', 'ma', 'crit_damage', 'crit_chance', 'bu', 'accuracy')
        }),
        ('Защита', {
            'fields': ('pz', 'physical_defense', 'magic_defense', 'physical_pierce', 'magic_pierce', 'dodge')
        }),
        ('Очки активности', {
            'fields': ('activity_points', 'spent_points'),
            'description': 'Управляйте очками активности здесь или на специальной странице'
        }),
    )
    extra = 0
    max_num = 1
    min_num = 1


class UserAdmin(BaseUserAdmin):
    inlines = [ProfileInline]

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('activity-management/', admin_views.activity_management, name='activity_management'),
            path('activity/update/', admin_views.update_activity_points, name='update_activity_points'),
        ]
        return custom_urls + urls

# Создаем кастомный ModelAdmin для отображения в меню
class ActivityManagementAdmin(admin.ModelAdmin):
    """Фейковый ModelAdmin для отображения пункта в меню"""

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
        """Перенаправляем на страницу управления активностью"""
        from django.shortcuts import redirect
        return redirect('admin:activity_management')


# Регистрируем User с кастомным админом
admin.site.unregister(User)
admin.site.register(User, UserAdmin)

# Регистрируем фейковую модель для отображения в меню
from django.contrib.admin import SimpleListFilter


class DummyModel(models.Model):
    class Meta:
        managed = False
        verbose_name = 'Таблица активности'
        verbose_name_plural = 'Таблица активности'
        app_label = 'auth'  # Помещаем в раздел "Пользователи и группы"


# Регистрируем фейковую модель
admin.site.register(DummyModel, ActivityManagementAdmin)