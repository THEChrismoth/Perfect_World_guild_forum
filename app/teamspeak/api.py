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
    return JsonResponse({
        'tasks': [{'id': task.pk, 'type': task.type, 'payload': task.payload} for task in tasks],
        'track_presence': bool(attendance.active_sessions(now)),
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
    if data is None or not isinstance(data.get('clients'), list):
        return JsonResponse({'error': 'Ожидается {"clients": [...]}'}, status=400)
    now = timezone.now()
    marks = attendance.record_presence(data['clients'], now)
    attendance.finalize_due(now)
    return JsonResponse({'ok': True, 'marks': marks})


@bot_api
@require_GET
def license_file(request):
    ts_settings = TeamSpeakSettings.load()
    if not ts_settings.license_data:
        return JsonResponse({'error': 'Лицензия не загружена'}, status=404)
    response = HttpResponse(bytes(ts_settings.license_data), content_type='application/octet-stream')
    response['Content-Disposition'] = 'attachment; filename="licensekey.dat"'
    return response
