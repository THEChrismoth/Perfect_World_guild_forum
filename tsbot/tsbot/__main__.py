"""Запуск бота: python -m tsbot [run|setup].

run   — настроить сервер по channels.json и работать с сайтом (по умолчанию)
setup — только настроить сервер и выйти
"""
import os
import sys
from functools import partial

from .bot import Bot
from .query import QueryError, connect
from .setup import Setup, load_config
from .site_api import SiteApi


def log(message):
    print(message, flush=True)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'run'
    password = os.environ.get('TS3_SERVERADMIN_PASSWORD', '')
    if not password:
        raise SystemExit('Не задан TS3_SERVERADMIN_PASSWORD в .env')
    config = load_config(os.environ.get('CHANNELS_CONFIG', '/app/channels.json'))

    connect_query = partial(
        connect,
        os.environ.get('TS3_HOST', 'teamspeak'),
        int(os.environ.get('TS3_QUERY_PORT', '10011')),
        password,
        os.environ.get('BOT_NICKNAME', 'Бот гильдии'),
        log=log,
    )
    try:
        query = connect_query()
    except QueryError as error:
        raise SystemExit(f'Не удалось войти в ServerQuery: {error}. Проверьте TS3_SERVERADMIN_PASSWORD')

    Setup(query, config, log=log).run()
    if mode == 'setup':
        query.close()
        return

    token = os.environ.get('TSBOT_API_TOKEN', '')
    if not token:
        log('TSBOT_API_TOKEN не задан — бот только настроил комнаты. Чтобы связать TeamSpeak с сайтом, '
            'задайте TSBOT_API_TOKEN в .env и выполните docker compose up -d')
        query.close()
        return

    bot = Bot(connect_query, SiteApi(os.environ.get('SITE_URL', 'http://web:8000'), token), config,
              ts_data_dir=os.environ.get('TS3_DATA_DIR', '/ts3data'), log=log)
    bot.query = query
    log('Бот запущен: жду задач от сайта')
    bot.run_forever()


if __name__ == '__main__':
    main()
