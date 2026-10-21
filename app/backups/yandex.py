"""Минимальный клиент REST API Яндекс Диска: https://yandex.ru/dev/disk-api/doc/ru/

Загрузка файла — два шага: запросить у API адрес для загрузки, затем отправить файл PUT-запросом.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

API_URL = 'https://cloud-api.yandex.net/v1/disk'
TIMEOUT = 60
UPLOAD_TIMEOUT = 600


class YandexDiskError(Exception):
    pass


class YandexDisk:
    def __init__(self, token):
        self.token = token

    def _request(self, method, endpoint, params=None, ok_statuses=(200, 201, 202, 204)):
        url = f'{API_URL}{endpoint}'
        if params:
            url += '?' + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, method=method, headers={
            'Authorization': f'OAuth {self.token}',
            'Accept': 'application/json',
        })
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                body = response.read()
                status = response.status
        except urllib.error.HTTPError as error:
            status = error.code
            body = error.read()
            if status in ok_statuses:
                return status, _parse(body)
            raise YandexDiskError(_error_message(status, body)) from None
        except urllib.error.URLError as error:
            raise YandexDiskError(f'Нет связи с Яндекс Диском: {error.reason}') from None

        if status not in ok_statuses:
            raise YandexDiskError(_error_message(status, body))
        return status, _parse(body)

    def check(self):
        """Проверяет токен. Возвращает сведения о Диске (место, владелец)."""
        _, data = self._request('GET', '/')
        return data

    def ensure_folder(self, path):
        """Создает папку и все родительские папки, если их нет."""
        prefix, _, rest = path.partition(':/')
        current = f'{prefix}:/'
        for part in [p for p in rest.split('/') if p]:
            current = current.rstrip('/') + '/' + part
            # 409 — папка уже существует.
            self._request('PUT', '/resources', {'path': current}, ok_statuses=(201, 409))

    def upload(self, local_path, remote_path):
        _, data = self._request('GET', '/resources/upload', {'path': remote_path, 'overwrite': 'true'})
        href = data.get('href')
        if not href:
            raise YandexDiskError('Яндекс Диск не вернул адрес для загрузки')

        size = os.path.getsize(local_path)
        with open(local_path, 'rb') as file:
            request = urllib.request.Request(href, data=file, method='PUT', headers={
                'Content-Length': str(size),
                'Content-Type': 'application/octet-stream',
            })
            try:
                with urllib.request.urlopen(request, timeout=UPLOAD_TIMEOUT) as response:
                    status = response.status
            except urllib.error.HTTPError as error:
                raise YandexDiskError(_error_message(error.code, error.read())) from None
            except urllib.error.URLError as error:
                raise YandexDiskError(f'Не удалось загрузить файл: {error.reason}') from None

        if status not in (201, 202):
            raise YandexDiskError(f'Не удалось загрузить файл (код {status})')

    def list_files(self, folder):
        """Файлы в папке: список словарей с ключами name, path, created."""
        _, data = self._request('GET', '/resources', {
            'path': folder,
            'limit': 1000,
            'fields': '_embedded.items.name,_embedded.items.path,_embedded.items.type,_embedded.items.created',
        })
        items = (data.get('_embedded') or {}).get('items') or []
        return [item for item in items if item.get('type') == 'file']

    def delete(self, path):
        # 404 — файла уже нет, это не ошибка.
        self._request('DELETE', '/resources', {'path': path, 'permanently': 'true'}, ok_statuses=(202, 204, 404))

    def download(self, remote_path, local_path):
        _, data = self._request('GET', '/resources/download', {'path': remote_path})
        href = data.get('href')
        if not href:
            raise YandexDiskError('Яндекс Диск не вернул адрес для скачивания')
        try:
            with urllib.request.urlopen(href, timeout=UPLOAD_TIMEOUT) as response, open(local_path, 'wb') as file:
                while chunk := response.read(1024 * 1024):
                    file.write(chunk)
        except urllib.error.URLError as error:
            raise YandexDiskError(f'Не удалось скачать файл: {getattr(error, "reason", error)}') from None


def _parse(body):
    if not body:
        return {}
    try:
        return json.loads(body)
    except ValueError:
        return {}


def _error_message(status, body):
    data = _parse(body)
    description = data.get('description') or data.get('message') or ''
    if status == 401:
        return 'Токен Яндекса недействителен или истек. Получите новый токен'
    if status == 403:
        return 'У токена нет доступа к этой папке. Проверьте права приложения и путь к папке'
    if status == 507:
        return 'На Яндекс Диске закончилось место'
    return f'Ошибка Яндекс Диска (код {status}){": " + description if description else ""}'
