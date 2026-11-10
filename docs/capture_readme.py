"""Снимает темы через Playwright на временной демонстрационной базе.

Запуск: uv run --with playwright python docs/capture_readme.py
Перед первым запуском: python -m playwright install chromium
"""
import base64
import os
from pathlib import Path
import sys
import tempfile
import threading
from wsgiref.simple_server import make_server, WSGIRequestHandler

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs' / 'images'
COLORS = [('indigo', 'Индиго', '#818cf8'), ('blue', 'Синий', '#60a5fa'),
          ('teal', 'Бирюзовый', '#2dd4bf'), ('pink', 'Розовый', '#f472b6'),
          ('orange', 'Оранжевый', '#fb923c')]


def main():
    with tempfile.TemporaryDirectory(prefix='guild-readme-') as temporary:
        os.environ.update(DEBUG='True', DEMO_MODE='False', USE_HTTPS='False',
                          ALLOWED_HOSTS='127.0.0.1,localhost,testserver',
                          DATABASE_URL='sqlite:///' + Path(temporary, 'demo.sqlite3').as_posix(),
                          DJANGO_SETTINGS_MODULE='config.settings')
        sys.path.insert(0, str(ROOT / 'app'))
        import django
        django.setup()
        from django.conf import settings
        from django.core.management import call_command
        from django.test import Client, override_settings
        from django.contrib.auth.models import User
        from django.contrib.staticfiles.handlers import StaticFilesHandler
        from django.core.wsgi import get_wsgi_application
        from django.db import connections
        settings.DATABASES['default']['CONN_MAX_AGE'] = 0
        settings.MEDIA_ROOT = str(Path(temporary, 'media'))
        call_command('migrate', verbosity=0)
        with override_settings(DEMO_MODE=True):
            call_command('demo_seed', verbosity=0)
        user = User.objects.get(username='Северянка')
        user.is_superuser = True
        user.save()
        client = Client()
        client.force_login(user)

        class QuietHandler(WSGIRequestHandler):
            def log_message(self, *args):
                pass

        server = make_server('127.0.0.1', 0, StaticFilesHandler(get_wsgi_application()),
                             handler_class=QuietHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f'http://127.0.0.1:{server.server_port}'
        from playwright.sync_api import sync_playwright
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel='chromium')
                context = browser.new_context(viewport={'width': 1440, 'height': 940},
                                              device_scale_factor=1, locale='ru-RU')
                context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                                     'value': client.cookies[settings.SESSION_COOKIE_NAME].value,
                                     'url': url}])
                page = context.new_page()
                for section, route in [('forum', '/'), ('admin', '/admin/')]:
                    stacks = []
                    for theme, title in [('dark', 'Тёмная тема'), ('light', 'Светлая тема')]:
                        page.goto(url + route)
                        page.evaluate('(theme) => localStorage.setItem("theme", theme)', theme)
                        page.reload()
                        page.wait_for_function('(theme) => document.documentElement.dataset.theme === theme', arg=theme)
                        page.evaluate('document.fonts.ready')
                        shots = []
                        for color, label, swatch in COLORS:
                            if section == 'forum':
                                page.locator('.site-account-toggle').click()
                                selector = f'[data-accent-form] button[value="{color}"]'
                            else:
                                page.locator('.ga-user-menu > summary').click()
                                selector = f'[data-ga-accent-form] button[value="{color}"]'
                            with page.expect_response(lambda response: 'accent' in response.url and response.request.method == 'POST'):
                                page.locator(selector).click()
                            page.locator('details[open]').evaluate_all('(items) => items.forEach(item => item.open = false)')
                            page.wait_for_timeout(450)
                            assert page.locator('html').get_attribute('data-accent') == color
                            raw = page.screenshot(animations='disabled')
                            shots.append((label, swatch, base64.b64encode(raw).decode()))
                            if color == 'indigo':
                                (OUT / f'preview-{section}-{theme}.png').write_bytes(raw)
                        stacks.append((title, shots))
                    compose(context, section, stacks)
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            connections.close_all()


def compose(context, section, stacks):
    """Собирает каскад снимков с диагональным разделением тем в каждом слое."""
    cards = []
    dark, light = stacks[0][1], stacks[1][1]
    for index, ((label, color, dark_data), (_, _, light_data)) in enumerate(zip(dark, light)):
        cards.append(f'''<article style="left:{52 + index * 48}px;top:{82 + index * 96}px">
            <header><i style="background:{color}"></i>{label}<span>ТЁМНАЯ ↙ &nbsp; / &nbsp; ↗ СВЕТЛАЯ</span></header>
            <div class="split">
                <img src="data:image/png;base64,{light_data}">
                <img class="dark" src="data:image/png;base64,{dark_data}">
                <div class="divider"></div>
            </div></article>''')
    page = context.new_page()
    page.set_viewport_size({'width': 1440, 'height': 1280})
    page.set_content('''<!doctype html><meta charset="utf-8"><style>
        *{box-sizing:border-box}body{margin:0;background:#101522;color:#e5eaf5;font-family:Arial,sans-serif}
        h2{position:absolute;top:26px;left:52px;margin:0;font-size:22px;font-weight:600;letter-spacing:.5px}
        article{position:absolute;width:1140px;border:1px solid #596179;border-radius:12px;overflow:hidden;
        background:#202736;box-shadow:0 12px 32px #0008}header{height:38px;display:flex;align-items:center;
        gap:10px;padding:0 14px;font-size:15px;font-weight:600}i{width:12px;height:12px;border-radius:50%}
        span{margin-left:auto;color:#a4aec4;font-size:10px;letter-spacing:1.5px}
        .split{position:relative}img{display:block;width:100%}
        .dark{position:absolute;inset:0;clip-path:polygon(0 0,65% 0,35% 100%,0 100%)}
        .divider{position:absolute;inset:0;background:#cbd5e180;
        clip-path:polygon(64.9% 0,65.1% 0,35.1% 100%,34.9% 100%)}
        </style><h2>PERFECT WORLD · ПЯТЬ ЦВЕТОВ, ДВЕ ТЕМЫ</h2>''' + ''.join(cards))
    page.locator('img').evaluate_all('(images) => Promise.all(images.map(image => image.decode()))')
    page.screenshot(path=str(OUT / f'preview-{section}.png'), animations='disabled')
    page.close()


if __name__ == '__main__':
    main()
