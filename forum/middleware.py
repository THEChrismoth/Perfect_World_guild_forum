from django.utils import timezone

class UserActivityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Обновляем время активности только для авторизованных пользователей
        if request.user.is_authenticated:
            try:
                profile = request.user.profile
                profile.last_activity = timezone.now()
                # Используем update_fields для оптимизации
                profile.save(update_fields=['last_activity'])
            except Exception as e:
                # Если профиля нет по какой-то причине, игнорируем
                pass

        return response