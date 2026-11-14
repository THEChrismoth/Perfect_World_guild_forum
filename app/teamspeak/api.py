"""HTTP API для бота TeamSpeak (tsbot/). Бот обращается к нему изнутри сети Docker.

Авторизация — заголовок «Authorization: Bearer <TSBOT_API_TOKEN>» (токен задаётся в .env).
Если токен не задан, API отключено.

GET  /api/tsbot/state/            — отметка «бот на связи», задачи для выполнения, нужно ли слать присутствие
POST /api/tsbot/tasks/<id>/       — результат задачи: {"ok": true, "data": {...}} или {"ok": false, "error": "..."}
POST /api/tsbot/presence/         — кто в каких каналах во время ивента (раз в минуту):
                                    {"clients": [{"uid": "...", "path": ["Гильдия", ...]}]}
GET  /api/tsbot/license/          — файл лицензии TeamSpeak (для задачи install_license)
"""
import datetime
import hmac
import json
import logging
from functools import wraps

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from . import attendance
from .models import TeamSpeakSettings, TsTask
from .tasks import apply_task_result
from skirmishes.models import Skirmish
from skirmishes.presence import record_presence as record_skirmish_presence

logger = logging.getLogger(__name__)
MAX_TASKS_PER_POLL = 20
# Задача, которую бот взял, но не отчитался (например, перезапустился), возвращается в очередь.
STALE_TASK_AFTER = datetime.timedelta(minutes=10)


def bot_api(view):
    # Бот не входит в аккаунт — его пускает токен, а не сессия, поэтому вход на сайт здесь не нужен.
    @login_not_required
    @csrf_exempt
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        expected = settings.TSBOT_API_TOKEN
        if not expected:
            return JsonResponse({'error': 'API бота отключено: не задан TSBOT_API_TOKEN'}, status=403)
        header = request.headers.get('Authorization', '')
        token = header[len('Bearer '):] if header.startswith('Bearer ') else ''
        if not hmac.compare_digest(token.encode(), expected.encode()):
            return JsonResponse({'error': 'Неверный токен'}, status=403)
        return view(request, *args, **kwargs)
    return wrapper


def _json_body(request):
    try:
        return json.loads(request.body or b'{}')
    except ValueError:
        return None


@bot_api
@require_GET
def state(request):
    now = timezone.now()
    TeamSpeakSettings.objects.update_or_create(pk=1, defaults={'bot_last_seen': now})

    TsTask.objects.filter(status='running', started_at__lt=now - STALE_TASK_AFTER).update(status='pending')
    with transaction.atomic():
        tasks = list(TsTask.objects.select_for_update().filter(status='pending').order_by('created_at')[:MAX_TASKS_PER_POLL])
        TsTask.objects.filter(pk__in=[task.pk for task in tasks]).update(status='running', started_at=now)

    attendance.finalize_due(now)
    sessions = attendance.active_sessions(now)
    skirmish_id = Skirmish.objects.filter(ended_at__isnull=True).values_list('pk', flat=True).first()
    return JsonResponse({
        'tasks': [{'id': task.pk, 'type': task.type, 'payload': task.payload} for task in tasks],
        'track_presence': bool(sessions) or skirmish_id is not None,
        'active_skirmish_id': skirmish_id,
        'presence_key': f"{skirmish_id or ''}:" + ','.join(str(session.pk) for session in sessions),
    })


@bot_api
@require_POST
def task_result(request, task_id):
    data = _json_body(request)
    if data is None:
        return JsonResponse({'error': 'Ожидается JSON'}, status=400)
    try:
        task = TsTask.objects.get(pk=task_id)
    except TsTask.DoesNotExist:
        return JsonResponse({'error': 'Задача не найдена'}, status=404)

    task.status = 'done' if data.get('ok') else 'failed'
    task.result = data.get('data') or None
    task.error = (data.get('error') or '')[:2000]
    task.finished_at = timezone.now()
    task.save()
    apply_task_result(task)
    return JsonResponse({'ok': True})


@bot_api
@require_POST
def presence(request):
    data = _json_body(request)
    if not isinstance(data, dict) or not isinstance(data.get('clients'), list):
        return JsonResponse({'error': 'Ожидается {"clients": [...]}'}, status=400)
    clients = data['clients']
    if len(clients) > 2000 or any(
        not isinstance(client, dict)
        or not isinstance(client.get('uid'), str) or not 1 <= len(client['uid']) <= 64
        or not isinstance(client.get('path'), list) or len(client['path']) > 32
        or any(not isinstance(part, str) or len(part) > 255 for part in client['path'])
        or not isinstance(client.get('nickname', ''), str) or len(client.get('nickname', '')) > 128
        for client in clients
    ):
        return JsonResponse({'error': 'Некорректный список клиентов TS'}, status=400)
    session_id = data.get('skirmish_id')
    if session_id is not None and (type(session_id) is not int or session_id < 1):
        return JsonResponse({'error': 'Некорректный номер замеса'}, status=400)
    now = timezone.now()
    marks = attendance.record_presence(data['clients'], now)
    skirmish_marks = record_skirmish_presence(clients, session_id, now)
    attendance.finalize_due(now)
    return JsonResponse({'ok': True, 'marks': marks, 'skirmish_marks': skirmish_marks})


@bot_api
@require_GET
def license_file(request):
    ts_settings = TeamSpeakSettings.load()
    if not ts_settings.license_data:
        return JsonResponse({'error': 'Лицензия не загружена'}, status=404)
    response = HttpResponse(bytes(ts_settings.license_data), content_type='application/octet-stream')
    response['Content-Disposition'] = 'attachment; filename="licensekey.dat"'
    return response
