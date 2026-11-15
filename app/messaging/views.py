import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import OperationalError
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables

from .crypto import MessageCryptoError, configured
from .forms import MessageForm
from .models import ContactBlock
from .selectors import dialog_rows, dialogs_for, message_data
from .services import can_contact, contact_queryset, mark_read, own_conversations, send_message, set_block, unread_count


def _number(value, default=0):
    try:
        result = int(value)
        if result < 0 or result > 9223372036854775807:
            raise ValueError
        return result
    except (ValueError, TypeError):
        return default


def _dialog(request, pk):
    return get_object_or_404(own_conversations(request.user).select_related(
        'low_user__profile', 'high_user__profile'), pk=pk)


def _sidebar(request):
    page = Paginator(dialogs_for(request.user), 20).get_page(request.GET.get('page'))
    return {'dialog_page': page, 'dialog_rows': dialog_rows(request.user, page),
            'current_dialog_id': request.resolver_match.kwargs.get('pk')}


@login_required
@never_cache
@require_GET
def inbox(request):
    data = _sidebar(request)
    if request.GET.get('partial') == '1':
        return JsonResponse({'sidebar': render_to_string('messaging/sidebar.html', data, request=request),
                             'unread': unread_count(request.user)})
    return render(request, 'messaging/inbox.html', data)


@login_required
@never_cache
@require_GET
def contacts(request):
    query = request.GET.get('q', '').strip()[:50]
    users = contact_queryset(request.user)
    if query:
        users = users.filter(username__icontains=query)
    return render(request, 'messaging/contacts.html', {'contacts': users[:20], 'query': query})


@sensitive_variables()
def _send_form(request, recipient, form):
    status = 400
    if form.is_valid():
        try:
            message, created = send_message(request.user, recipient, form.cleaned_data['body'], form.cleaned_data['client_id'])
            if request.headers.get('Accept') == 'application/json':
                return JsonResponse({'message': message_data(message, request.user),
                                     'client_id': str(uuid.uuid4())}, status=201 if created else 200), 0
            return redirect(message.conversation), 0
        except ValidationError as error:
            form.add_error(None, error)
        except PermissionDenied:
            form.add_error(None, 'Отправка сообщений в этот диалог недоступна.')
            status = 403
        except (MessageCryptoError, OperationalError):
            form.add_error(None, 'Не удалось отправить сообщение. Попробуйте позже.')
            status = 503
    if request.headers.get('Accept') == 'application/json':
        errors = [str(error) for values in form.errors.values() for error in values]
        return JsonResponse({'errors': errors}, status=status), 0
    return None, status


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
@sensitive_post_parameters('body')
@sensitive_variables()
def compose(request, user_id):
    recipient = get_object_or_404(contact_queryset(request.user), pk=user_id)
    existing = own_conversations(request.user).filter(low_user_id=min(request.user.pk, recipient.pk),
                                                      high_user_id=max(request.user.pk, recipient.pk)).first()
    if existing and request.method == 'GET':
        return redirect(existing)
    form = MessageForm(request.POST if request.method == 'POST' else None)
    status = 200
    if request.method == 'POST':
        response, status = _send_form(request, recipient, form)
        if response is not None:
            return response
    return render(request, 'messaging/compose.html', {**_sidebar(request), 'recipient': recipient,
                  'form': form, 'messaging_configured': configured()}, status=status)


def _conversation_page(request, dialog, form=None, status=200):
    before = _number(request.GET.get('before'))
    items = dialog.messages.order_by('-pk')
    if before:
        items = items.filter(pk__lt=before)
    items = list(items[:51])
    more = len(items) > 50
    items = list(reversed(items[:50]))
    other = dialog.other(request.user)
    return render(request, 'messaging/conversation.html', {
        **_sidebar(request), 'dialog': dialog, 'recipient': other, 'current_dialog_id': dialog.pk,
        'message_rows': [message_data(item, request.user, dialog) for item in items],
        'form': form or MessageForm(), 'messaging_configured': configured(),
        'can_send': can_contact(request.user, other),
        'blocked_by_me': ContactBlock.objects.filter(blocker=request.user, blocked=other).exists(),
        'history': bool(before), 'older_before': items[0].pk if more else None,
        'last_id': items[-1].pk if items else 0,
    }, status=status)


@login_required
@never_cache
@require_GET
def conversation(request, pk):
    return _conversation_page(request, _dialog(request, pk))


@login_required
@never_cache
@require_POST
@sensitive_post_parameters('body')
@sensitive_variables()
def send(request, pk):
    dialog = _dialog(request, pk)
    form = MessageForm(request.POST)
    response, status = _send_form(request, dialog.other(request.user), form)
    return response if response is not None else _conversation_page(request, dialog, form, status)


@login_required
@never_cache
@require_POST
def block(request, pk):
    dialog = _dialog(request, pk)
    action = request.POST.get('action')
    if action not in ('block', 'unblock'):
        return HttpResponseBadRequest('Некорректное действие')
    set_block(request.user, dialog.other(request.user), action == 'block')
    messages.success(request, 'Пользователь заблокирован' if action == 'block' else 'Блокировка снята')
    return redirect(dialog)


@login_required
@never_cache
@require_GET
def updates(request, pk):
    dialog = _dialog(request, pk)
    after = _number(request.GET.get('after'))
    items = list(dialog.messages.filter(pk__gt=after).order_by('pk')[:51])
    return JsonResponse({'messages': [message_data(item, request.user, dialog) for item in items[:50]],
                         'more': len(items) > 50, 'read_id': dialog.read_cursor(dialog.other(request.user)),
                         'unread': unread_count(request.user), 'can_send': can_contact(request.user, dialog.other(request.user))})


@login_required
@never_cache
@require_POST
def read(request, pk):
    dialog = _dialog(request, pk)
    try:
        mark_read(dialog.pk, request.user, _number(request.POST.get('up_to')))
    except ValidationError:
        return JsonResponse({'error': 'Сообщение не найдено'}, status=400)
    if request.headers.get('Accept') == 'application/json':
        return JsonResponse({'unread': unread_count(request.user)})
    return redirect(dialog)


@login_required
@never_cache
@require_GET
def badge(request):
    return JsonResponse({'unread': unread_count(request.user)})
