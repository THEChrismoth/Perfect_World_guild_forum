from django.conf import settings

from .accounts import DEMO_ROLES


def demo(request):
    if not settings.DEMO_MODE:
        return {'demo_mode': False}
    current_role = next(
        (key for key, role in DEMO_ROLES.items() if role['username'] == request.user.get_username()), None
    )
    return {'demo_mode': True, 'demo_roles': DEMO_ROLES, 'demo_current_role': current_role}
