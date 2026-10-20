# Разработка

## Стек

Python 3.13+, Django 6, PostgreSQL (в Docker) или SQLite (локально), Pillow, cryptography, gunicorn, Caddy.

## Структура репозитория

```
├── src/                  весь сайт (Django)
│   ├── manage.py
│   ├── config/           настройки и корневые URL
│   ├── core/             настройки сайта: название, favicon, почта, капча, шифрование секретов
│   ├── forum/            форум, права доступа к разделам
│   ├── profiles/         профили, регистрация, таблица очков активности
│   ├── reception/        заявки в гильдию и голосование
│   ├── auction/          аукцион за очки активности
│   ├── events/           ивенты, отряды, приглашения
│   ├── koslist/          кос-лист
│   ├── notifications/    уведомления
│   ├── backups/          резервные копии (сервер + Яндекс Диск)
│   ├── templates/
│   └── static_src/       исходники статики (CSS, иконки)
├── docker/               Caddyfile и entrypoint.sh
├── docs/
├── Dockerfile, docker-compose.yml, .env.example
└── pyproject.toml, uv.lock, requirements.txt
```

`.env`, `db.sqlite3`, `media/` и собранная статика `static/` лежат в корне репозитория, а не в `src/`.

**PyCharm:** пометьте папку `src` как Sources Root (правый клик → *Mark Directory as* → *Sources Root*), а в конфигурации запуска Django укажите `src/manage.py` и рабочую папку `src`.

## Запуск без Docker

Удобно при правке кода: изменения подхватываются сразу. Используется отдельная база SQLite (`db.sqlite3`), с Docker-базой она не связана.

```bash
uv sync
# или: python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt
```

Создайте `.env` в корне репозитория:

```env
DEBUG=True
DJANGO_SECRET_KEY=любая-длинная-строка
```

Команды Django запускаются из папки `src`:

```bash
cd src
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Сайт — http://127.0.0.1:8000/, админ-панель — http://127.0.0.1:8000/admin/. Без `DEBUG=True` не будут работать стили и картинки. Пока почта не настроена в админке (Настройки сайта → Почта), письма выводятся в консоль.

## Переменные окружения вне Docker

В Docker их выставляет `docker-compose.yml`, при запуске без Docker — задайте в `.env` сами:

| Переменная | Описание |
|---|---|
| `DEBUG` | `True` для разработки. По умолчанию `False` |
| `ALLOWED_HOSTS` | Домены через запятую (нужно при `DEBUG=False`) |
| `CSRF_TRUSTED_ORIGINS` | По умолчанию строится из `ALLOWED_HOSTS` |
| `DATABASE_URL` | Например `postgres://user:pass@localhost:5432/forum`. По умолчанию SQLite |
| `USE_HTTPS` | `True`, если сайт работает по HTTPS: редирект на https и secure-куки |

## Тесты

```bash
cd src
python manage.py test
```

## Миграции

```bash
cd src
python manage.py makemigrations
```

Модели должны принадлежать приложениям проекта. Не указывайте `app_label` встроенных приложений Django (`auth` и т. п.) — иначе миграция создастся внутри установленного Django в `.venv` и не попадёт в репозиторий.

## Статика

Исходники — в `src/static_src/`, `collectstatic` собирает их в `static/` в корне репозитория (в Docker это делается при старте контейнера `web`).

## Перенос данных со старой установки (SQLite → Docker)

Сделайте резервную копию `db.sqlite3` и `media/`. На старой установке (в версиях до переноса кода в `src/` файл `manage.py` лежит в корне):

```bash
python manage.py dumpdata --natural-foreign --natural-primary \
    -e contenttypes -e auth.permission -e admin.logentry -e sessions > data.json
```

На новой (после `docker compose up -d`):

```bash
docker compose cp data.json web:/app/data.json
docker compose exec web python manage.py loaddata /app/data.json
docker compose cp ./media/. web:/app/media/
```

## Docker-файлы

| Файл | Назначение |
|---|---|
| `Dockerfile` | Образ сайта (Django + gunicorn). Внутри та же структура: код в `/app/src`, данные в `/app/static` и `/app/media` |
| `docker/entrypoint.sh` | Миграции, `collectstatic` и создание администратора при старте |
| `docker/Caddyfile` | HTTPS, раздача `/static` и `/media`, проксирование в Django |
| `docker-compose.yml` | Сервисы `db`, `web`, `scheduler` (резервные копии), `caddy` и тома с данными; `teamspeak` и `tsbot` — в профиле `teamspeak` |
| `tsbot/` | Бот TeamSpeak — отдельный сервис со своим `Dockerfile`; `channels.json` — группы и комнаты |

## Резервные копии

Приложение `backups`. Копии создает только контейнер `scheduler` (`manage.py run_backup_scheduler`): раз в 30 секунд он проверяет расписание и очередь. Кнопка в админке лишь ставит копию в очередь — так копирование не блокирует gunicorn и не запускается в нескольких процессах сразу. Без Docker планировщик можно запустить той же командой или делать копии через `manage.py backup_now`.

Архив `backup-ГГГГММДД-ЧЧММСС.tar.gz`: `manifest.json`, дамп базы (`pg_dump --format=custom` для PostgreSQL, копия файла для SQLite) и `media/`. Копии лежат в `BACKUP_DIR` (по умолчанию `backups/` в корне репозитория, в Docker — том `backups`), с правами `600`. Клиент Яндекс Диска (`backups/yandex.py`) написан на стандартной библиотеке.

**Шифрование** (`backups/crypto.py`):

- При заданном `BACKUP_ENCRYPTION_PASSWORD` архив шифруется `gpg --symmetric` (AES-256, S2K SHA-512) в `.tar.gz.gpg`. Открытый архив собирается во временной папке и в `BACKUP_DIR` не попадает. Стандартный формат выбран намеренно: копию можно открыть без сайта.
- Незашифрованные копии на Яндекс Диск не загружаются (проверка и в форме настроек, и в `run_backup`).
- Токен Яндекса хранится в поле `yandex_token` как `fernet:...` (ключ — HKDF от `SECRET_KEY`). Читать только через `BackupSettings.get_yandex_token()`; `save()` сам шифрует открытое значение.
- Тесты подменяют gpg; проверка с настоящим gpg (`RealGpgTests`) пропускается, если он не работает. gpg из Git для Windows для этого не подходит (не запускается gpg-agent), поэтому полный прогон — в контейнере: `docker compose exec web python manage.py test backups`. Путь к другому gpg можно задать в `BACKUP_GPG_BINARY`.

## Почта, капча и секреты

- **Почта** — `core/mail.py`: `send_site_mail()` берёт SMTP из `SiteSettings` (админка). Если почта не настроена, используется консольный бэкенд. `EMAIL_*` в `.env` больше не читаются.
- **Капча** — `core/captcha.py`, [DDoS-Guard dCAPTCHA](https://ddos-guard.ru/tutorials/captcha/integration): виджет `ddg-captcha-container` добавляет в форму поле `ddg-captcha-token`, сервер проверяет его POST-запросом (JSON) на `https://captcha.ddos-guard.net/siteverify`. Проверка в `RegistrationForm.clean()` выполняется последней — токен одноразовый и не тратится на форму с другими ошибками. При недоступности сервиса регистрация блокируется.
- **Секреты в базе** — `core/secrets.py` (Fernet, ключ — HKDF от `SECRET_KEY`): пароль SMTP, Private key капчи, токен Яндекс Диска. Модели шифруют значения в `save()`, читать — через `get_*()`. Метку HKDF менять нельзя — сохранённые секреты перестанут расшифровываться.

## Админ-панель

Стандартная админка Django без сторонних тем. `core.apps.GuildAdminConfig` подключает `core/admin_site.py` вместо `django.contrib.admin`, поэтому `@admin.register` и `admin.site` работают как обычно.

- **Дашборд** — `core/dashboard.py` (данные; каждый блок — только при наличии прав) и `templates/admin/index.html`.
- **Порядок и иконки разделов** — `APP_ORDER` в `core/admin_site.py`.
- **Тема** — `static_src/admin/css/guild_theme.css`: переопределяет CSS-переменные Django для светлой (индиго) и тёмной (розовый) тем, поэтому работает встроенный переключатель темы. Для своих кнопок в шаблонах — классы `.btn .btn-primary/.btn-success/.btn-danger/.btn-outline-primary/.btn-outline-secondary`.
- Собственные страницы админки рендерятся с `**admin.site.each_context(request)` — иначе у них не будет шапки с названием сайта и бокового меню.

## Бот TeamSpeak (`tsbot/`)

Отдельный сервис без Django и сторонних библиотек — только стандартная библиотека Python, образ `python:3.13-alpine`. С сайтом связан только HTTP API, поэтому бот и сайт развиваются и перезапускаются независимо.

```
tsbot/
├── Dockerfile
├── channels.json        группы и комнаты (монтируется в контейнер — правки без пересборки)
├── tsbot/
│   ├── __main__.py      python -m tsbot [run|setup]
│   ├── query.py         клиент ServerQuery (экранирование, защита от флуда, повтор при ошибке 524)
│   ├── setup.py         группы и комнаты по channels.json — при каждом старте
│   ├── tree.py          пути каналов «Гильдия / МТВ / ГВГ»
│   ├── site_api.py      HTTP-клиент API сайта
│   └── bot.py           цикл: задачи сайта, присутствие в каналах, keepalive
└── tests/test_bot.py    тесты на поддельном сервере (FakeQuery)
```

Тесты бота: `cd tsbot && python -m unittest discover -s tests -t .`

**Связь с сайтом** (`src/teamspeak/`). Бот опрашивает сайт каждые 3 секунды, сайт бота не вызывает:

| Запрос | Что делает |
|---|---|
| `GET /api/tsbot/state/` | отметка «бот на связи», задачи из очереди `TsTask`, нужно ли слать присутствие |
| `POST /api/tsbot/tasks/<id>/` | результат задачи → `teamspeak/tasks.py: apply_task_result` |
| `POST /api/tsbot/presence/` | кто в каких каналах → `teamspeak/attendance.py` |
| `GET /api/tsbot/license/` | файл лицензии (хранится в базе, не в публичной `media`) |

Авторизация — `Authorization: Bearer <TSBOT_API_TOKEN>`; без токена API отключено. Бот ходит на `http://web:8000` внутри сети Docker (`web` добавлен в `ALLOWED_HOSTS`) с заголовком `X-Forwarded-Proto: https`, чтобы Django не перенаправлял на https. Задача, взятая ботом и не закрытая за 10 минут, возвращается в очередь.

**Задачи:** `verify_link` (личное сообщение со ссылкой подтверждения + тычок), `grant_guild` / `revoke_guild`, `create_room` / `delete_room` (комната в `rooms_parent`, владелец — Channel Admin), `install_license` (файл в том `teamspeak_data`, `serverprocessstop` — Docker перезапускает контейнер; если сервер не поднялся за 150 с — возврат прежней лицензии).

**Группы TeamSpeak 3:** группа по умолчанию для всех посетителей — `Guest` (переименовывается в `default_group_name`); группа гильдии — стандартная `Normal` (`guild_group_source`), TeamSpeak её сам не выдаёт. `guild_power` при старте сверяется с силой входа группы посетителей.

**Учёт ивентов** (`teamspeak/attendance.py`): окно — `EventNotification.start_time` + `duration_minutes`, каналы — `EventType.ts_channels`. Минута засчитывается один раз, даже если бот прислал отчёт чаще. Итоги подводятся при обращениях бота после окончания окна (`points_processed_at` защищает от повтора). Учитываются только подтверждённые привязки `TsLink`.

**Особенности ServerQuery:** защита от флуда пропускает около 10 команд за 3 секунды (пауза 0,35 с, права одного канала — одной командой через `|`); пустой результат приходит ошибкой 1281; пароль ServerQuery задаётся переменной образа `TS3SERVER_SERVERADMIN_PASSWORD` (её поддерживает entrypoint официального образа, хотя в документации она не описана).