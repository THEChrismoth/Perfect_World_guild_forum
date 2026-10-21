"""Капча DDoS-Guard (dCAPTCHA): https://ddos-guard.ru/tutorials/captcha/integration

На странице виджет добавляет в форму скрытое поле ddg-captcha-token. Сервер проверяет токен
POST-запросом на /siteverify с приватным ключом. Токен одноразовый.
"""
import json
import logging
import urllib.error
import urllib.request

from .models import SiteSettings

SCRIPT_URL = 'https://captcha.ddos-guard.net/static/api.js'
VERIFY_URL = 'https://captcha.ddos-guard.net/siteverify'
TOKEN_FIELD = 'ddg-captcha-token'
TIMEOUT = 10

logger = logging.getLogger(__name__)

ERROR_MESSAGES = {
    'missing-input-response': 'Пройдите проверку «Я не робот»',
    'timeout-or-duplicate': 'Проверка устарела — пройдите её ещё раз',
    'invalid-input-response': 'Проверка не пройдена — попробуйте ещё раз',
}
CONFIG_ERRORS = {'missing-input-secret', 'invalid-input-secret', 'bad-request'}


def verify_captcha(token, site_settings=None):
    """Проверяет токен капчи. Возвращает текст ошибки для пользователя или None, если проверка пройдена.

    Если сервис капчи недоступен, пользователь не пропускается: иначе бот мог бы
    проходить регистрацию, пока сервис не отвечает.
    """
    site_settings = site_settings or SiteSettings.load()
    if not token:
        return ERROR_MESSAGES['missing-input-response']

    body = json.dumps({'response': token, 'private_key': site_settings.get_captcha_private_key()}).encode()
    request = urllib.request.Request(
        VERIFY_URL, data=body, method='POST', headers={'Content-Type': 'application/json'}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            data = json.loads(response.read() or b'{}')
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        logger.warning('Капча DDoS-Guard недоступна: %s', error)
        return 'Не удалось проверить капчу — сервис временно недоступен. Попробуйте через минуту'

    if data.get('success') is True:
        return None

    codes = data.get('error-codes') or []
    if CONFIG_ERRORS.intersection(codes):
        logger.error('Капча DDoS-Guard: ошибка настройки ключей %s', codes)
        return 'Капча настроена неверно. Сообщите администратору сайта'
    for code in codes:
        if code in ERROR_MESSAGES:
            return ERROR_MESSAGES[code]
    return ERROR_MESSAGES['invalid-input-response']
