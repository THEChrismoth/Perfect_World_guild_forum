# profiles/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.urls import path
from django.urls import reverse
from django.utils.html import format_html
from django.contrib.admin import AdminSite
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


# Кастомный ModelAdmin для Profile
class ActivityModelAdmin(admin.ModelAdmin):
    # Меняем название модели в админке
    def get_model_perms(self, request):
        return {'add': False, 'change': False, 'delete': False, 'view': True}

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('', admin_views.activity_management, name='activity_management'),
        ]
        return custom_urls + urls


# Разрегистрируем User и зарегистрируем с нашим UserAdmin
admin.site.unregister(User)
admin.site.register(User, UserAdmin)

# Разрегистрируем Profile если зарегистрирован
try:
    admin.site.unregister(Profile)
except:
    pass

# Регистрируем Profile с кастомным админом
admin.site.register(Profile, ActivityModelAdmin)