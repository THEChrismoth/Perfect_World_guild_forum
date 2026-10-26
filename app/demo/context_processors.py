from django.conf import settings

from .accounts import DEMO_ROLES
from .guests import current_role


def demo(request):
    if not settings.DEMO_MODE:
        return {'demo_mode': False}
    return {'demo_mode': True, 'demo_roles': DEMO_ROLES, 'demo_current_role': current_role(request)}
