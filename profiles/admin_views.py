import json
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.models import User, Group
from django.contrib import messages
from django.contrib.admin import AdminSite
from django.views.decorators.csrf import csrf_exempt
from .models import Profile

@staff_member_required
def activity_management(request):
    # Получаем группу "Член гильдии"
    guild_group = Group.objects.filter(name='Член гильдии').first()

    # Получаем всех пользователей в группе "Член гильдии"
    if guild_group:
        users = User.objects.filter(groups=guild_group)
    else:
        users = User.objects.none()
        messages.warning(request, 'Группа "Член гильдии" не найдена. Создайте её в админ-панели.')

    # Сортируем по классу персонажа
    profiles = []
    for user in users:
        if hasattr(user, 'profile') and user.profile.player_class:
            profiles.append(user.profile)

    # Группируем по классам
    class_dict = {}
    for profile in profiles:
        class_name = profile.player_class
        if class_name not in class_dict:
            # Получаем русское название класса
            class_display = dict(Profile.CLASS_CHOICES).get(class_name, class_name)
            class_dict[class_name] = {
                'name': class_display,
                'icon': profile.get_icon_url(),
                'members': []
            }
        class_dict[class_name]['members'].append(profile)

    # Сортируем членов внутри каждого класса по имени пользователя
    for class_data in class_dict.values():
        class_data['members'].sort(key=lambda x: x.user.username)

    # Сортируем классы по названию
    sorted_classes = sorted(class_dict.items(), key=lambda x: x[1]['name'])

    context = {
        'class_dict': sorted_classes,
        'title': 'Управление активностью участников',
    }
    return render(request, 'admin/activity_management.html', context)

@staff_member_required
@csrf_exempt
def update_activity_points(request):
    """API для обновления очков активности"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            profile_id = data.get('profile_id')
            field = data.get('field')
            value = data.get('value')
            
            profile = get_object_or_404(Profile, id=profile_id)
            
            if field == 'current':
                # Установка текущего баланса
                if value is not None and value >= 0:
                    profile.activity_points = value
                    # Пересчитываем earned_points чтобы сохранить логику
                    profile.earned_points = profile.activity_points + profile.spent_points
                    profile.save()
                    return JsonResponse({
                        'success': True,
                        'current': profile.activity_points,
                        'spent': profile.spent_points,
                        'earned': profile.earned_points
                    })
            
            elif field == 'spent':
                # Корректировка потраченных очков
                if value is not None and value >= 0:
                    old_spent = profile.spent_points
                    delta = value - old_spent
                    profile.spent_points = value
                    profile.activity_points -= delta
                    if profile.activity_points < 0:
                        profile.activity_points = 0
                    # Пересчитываем earned_points
                    profile.earned_points = profile.activity_points + profile.spent_points
                    profile.save()
                    return JsonResponse({
                        'success': True,
                        'current': profile.activity_points,
                        'spent': profile.spent_points,
                        'earned': profile.earned_points
                    })
            
            elif field == 'earned':
                # Изменение начисленных очков
                if value is not None and value >= 0:
                    old_earned = profile.earned_points
                    delta = value - old_earned
                    profile.earned_points = value
                    # Увеличиваем текущие очки на дельту
                    profile.activity_points += delta
                    if profile.activity_points < 0:
                        profile.activity_points = 0
                    profile.save()
                    return JsonResponse({
                        'success': True,
                        'current': profile.activity_points,
                        'spent': profile.spent_points,
                        'earned': profile.earned_points
                    })
            
            return JsonResponse({'success': False, 'error': 'Invalid field or value'})
            
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    return JsonResponse({'success': False, 'error': 'Invalid method'})

class CustomAdminSite(AdminSite):
    def get_app_list(self, request):
        app_list = super().get_app_list(request)
        # Добавляем кастомный пункт в меню
        app_list.append({
            'name': 'Управление гильдией',
            'app_label': 'guild',
            'models': [{
                'name': 'Управление активностью',
                'object_name': 'ActivityManagement',
                'admin_url': reverse('admin:activity_management'),
                'view_only': True,
                'perms': {'change': True},
            }]
        })
        return app_list
