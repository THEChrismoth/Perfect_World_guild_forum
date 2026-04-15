from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin

class UserActivityMiddleware(MiddlewareMixin):
    def process_request(self, request):
        if request.user.is_authenticated:
            # Обновляем время последней активности
            request.user.profile.last_activity = timezone.now()
            request.user.profile.save(update_fields=['last_activity'])
