from .services import unread_count


def request_unread(request):
    """Повторно используем счётчик в шапке и боковом меню одного запроса."""
    if not hasattr(request, '_private_messages_unread'):
        request._private_messages_unread = unread_count(request.user)
    return request._private_messages_unread


def messaging_context(request):
    return {'private_messages_unread': request_unread(request)}
