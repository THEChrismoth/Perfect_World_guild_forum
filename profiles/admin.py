from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import Profile

class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    fieldsets = (
        ('Основная информация', {
            'fields': ('avatar', 'ts3_id', 'birth_date', 'city', 'player_class')
        }),
        ('Характеристики', {
            'fields': ('hp', 'mp', 'pa', 'ma', 'pz', 'bd', 'bu')
        }),
        ('Защита', {
            'fields': ('physical_defense', 'magic_defense', 'physical_pierce', 'magic_pierce')
        }),
        ('Криты и точность', {
            'fields': ('crit_damage', 'crit_chance', 'accuracy', 'dodge')
        }),
        ('Очки активности', {
            'fields': ('activity_points',),
            'description': 'Изменяйте очки активности здесь'
        }),
    )

class UserAdmin(BaseUserAdmin):
    inlines = [ProfileInline]

admin.site.unregister(User)
admin.site.register(User, UserAdmin)
