from datetime import timedelta

from django.utils import timezone

from profiles.models import Profile

# Как часто обновлять время активности. Онлайн считается по окну в 5 минут,
# так что писать в БД на каждый запрос не нужно
ACTIVITY_UPDATE_INTERVAL = timedelta(minutes=1)


class UserActivityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Обновляем время активности только для авторизованных пользователей
        if request.user.is_authenticated:
            now = timezone.now()
            # Один UPDATE без чтения профиля; срабатывает только если
            # с прошлого обновления прошло больше интервала
            Profile.objects.filter(user=request.user).exclude(
                last_activity__gt=now - ACTIVITY_UPDATE_INTERVAL
            ).update(last_activity=now)

        return response
