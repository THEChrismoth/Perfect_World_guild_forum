"""HTTP-клиент API сайта (app/teamspeak/api.py)."""
import json
import urllib.error
import urllib.request

TIMEOUT = 20


class SiteApiError(Exception):
    pass


class SiteApi:
    def __init__(self, base_url, token):
        self.base_url = base_url.rstrip('/')
        self.token = token

    def _request(self, method, path, data=None, raw=False):
        body = json.dumps(data).encode('utf-8') if data is not None else None
        request = urllib.request.Request(f'{self.base_url}/api/tsbot/{path}', data=body, method=method, headers={
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            # Бот ходит к сайту напрямую внутри сети Docker, минуя Caddy: сообщаем Django,
            # что исходное соединение защищённое, иначе он перенаправит на https.
            'X-Forwarded-Proto': 'https',
        })
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                content = response.read()
        except urllib.error.HTTPError as error:
            details = error.read().decode('utf-8', 'replace')[:300]
            raise SiteApiError(f'Сайт ответил {error.code}: {details}') from None
        except (urllib.error.URLError, OSError) as error:
            raise SiteApiError(f'Сайт недоступен: {getattr(error, "reason", error)}') from None
        if raw:
            return content
        try:
            return json.loads(content or b'{}')
        except ValueError:
            raise SiteApiError('Сайт вернул не JSON') from None

    def state(self):
        return self._request('GET', 'state/')

    def task_result(self, task_id, ok, data=None, error=''):
        return self._request('POST', f'tasks/{task_id}/', {'ok': ok, 'data': data or {}, 'error': error})

    def presence(self, clients):
        return self._request('POST', 'presence/', {'clients': clients})

    def license(self):
        return self._request('GET', 'license/', raw=True)
