# Forum Docker - README

Простой форум на Django в Docker контейнере с Nginx и PostgreSQL.

## Структура проекта

```
forum-docker/
├── app/                    # Django приложение
│   ├── forum/             # Основной проект Django
│   ├── forum_app/         # Приложение форума
│   ├── templates/         # HTML шаблоны
│   ├── static/           # Статические файлы
│   ├── media/            # Медиа файлы
│   ├── Dockerfile
│   ├── requirements.txt
│   └── manage.py
├── nginx/
│   └── default.conf       # Конфигурация Nginx
├── docker-compose.yml     # Docker Compose конфигурация
└── README.md
```

## Компоненты

- **PostgreSQL 15** - База данных для хранения данных форума
- **Django 4.2** - Веб-фреймворк для приложения форума
- **Nginx** - Веб-сервер для раздачи статики и проксирования запросов
- **Gunicorn** - WSGI сервер для запуска Django приложения

## Быстрый старт

### 1. Запуск проекта

```bash
cd forum-docker
docker-compose up -d --build
```

### 2. Создание суперпользователя

```bash
docker-compose exec app python manage.py createsuperuser
```

### 3. Доступ к форуму

- **Форум**: http://localhost
- **Админ панель**: http://localhost/admin/

## Управление данными

Данные сохраняются в Docker volumes и не удаляются при пересоздании контейнеров:

- `postgres_data` - данные PostgreSQL
- `static_volume` - статические файлы Django
- `media_volume` - медиа файлы пользователей

### Остановка проекта

```bash
docker-compose down
```

### Перезапуск проекта

```bash
docker-compose up -d
```

### Полное удаление (включая данные)

```bash
docker-compose down -v
```

## Переменные окружения

Вы можете изменить следующие параметры в `docker-compose.yml`:

- `POSTGRES_DB` - имя базы данных
- `POSTGRES_USER` - пользователь базы данных
- `POSTGRES_PASSWORD` - пароль базы данных
- `SECRET_KEY` - секретный ключ Django

## Функционал форума

- Категории и форумы
- Темы и сообщения
- Закрепленные темы
- Закрытые темы
- Подсчет количества сообщений
- Админ панель для модерации

## Добавление начальных данных

Через админ панель добавьте:
1. Категории форумов
2. Форумы в категориях
3. Пользователей

После этого пользователи смогут создавать темы и отвечать на сообщения.
