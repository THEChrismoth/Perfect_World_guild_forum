"""Основной цикл бота: задачи сайта и присутствие в каналах."""
import os
import time
from pathlib import Path

from .query import QueryError
from .setup import guild_channel_perms
from .site_api import SiteApiError
from .tree import channel_paths, find_channel

POLL_INTERVAL = 3          # Как часто спрашивать сайт о задачах, секунд
PRESENCE_INTERVAL = 60     # Как часто отправлять присутствие в каналах во время ивента
KEEPALIVE_INTERVAL = 120   # ServerQuery отключает молчащих через 300 секунд
RESTART_WAIT = 150         # Сколько ждать перезапуска TeamSpeak после установки лицензии

ERR_INVALID_CLIENT = (512, 1281, 1540)   # Клиента нет в базе TeamSpeak
ERR_DUPLICATE = 2561                     # Уже в группе
ERR_INVALID_CHANNEL = 768
ERR_NAME_IN_USE = 771


class TaskError(Exception):
    """Ошибка, понятная игроку — её текст увидит пользователь сайта."""


class Bot:
    def __init__(self, connect_query, api, config, ts_data_dir='/ts3data', log=print):
        self.connect_query = connect_query
        self.api = api
        self.config = config
        self.ts_data_dir = Path(ts_data_dir)
        self.log = log
        self.query = None
        self.last_presence = 0
        self.last_keepalive = time.time()
        self.handlers = {
            'verify_link': self.verify_link,
            'grant_guild': self.grant_guild,
            'revoke_guild': self.revoke_guild,
            'create_room': self.create_room,
            'delete_room': self.delete_room,
            'install_license': self.install_license,
        }

    # ----- служебное -----

    def ensure_connected(self):
        if self.query is None:
            self.query = self.connect_query()

    def reconnect(self):
        if self.query:
            self.query.close()
        self.query = None
        self.ensure_connected()

    def guild_group_id(self):
        name = self.config['guild_group']
        for group in self.query.command('servergrouplist'):
            if group['name'] == name and group.get('type') == '1':
                return group['sgid']
        raise TaskError(f'На сервере нет группы «{name}»')

    def client_db_id(self, uid):
        try:
            return self.query.command('clientgetdbidfromuid', cluid=uid)[0]['cldbid']
        except QueryError as error:
            if error.error_id in ERR_INVALID_CLIENT:
                raise TaskError('Клиент с этим TS3 ID ещё не заходил на сервер TeamSpeak — '
                                'подключитесь к серверу и повторите') from None
            raise

    def online_clients(self):
        return [c for c in self.query.command('clientlist', '-uid') if c.get('client_type') == '0']

    # ----- задачи -----

    def verify_link(self, payload):
        clients = [c for c in self.online_clients() if c.get('client_unique_identifier') == payload['uid']]
        if not clients:
            raise TaskError('Вы не подключены к TeamSpeak: клиент с вашим TS3 ID не найден в сети. '
                            'Подключитесь к серверу и нажмите кнопку ещё раз')
        message = (f'Сайт гильдии: подтвердите, что это ваш TeamSpeak, для аккаунта {payload["username"]} — '
                   f'откройте ссылку, войдя на сайт: [URL]{payload["url"]}[/URL]')
        for client in clients:
            self.query.command('sendtextmessage', targetmode=1, target=client['clid'], msg=message)
            # Тычок привлекает внимание: личное сообщение легко не заметить.
            self.query.command('clientpoke', clid=client['clid'], msg='Сайт гильдии: откройте личное сообщение от бота')
        return {'clients': len(clients)}

    def grant_guild(self, payload):
        group_id = self.guild_group_id()
        db_id = self.client_db_id(payload['uid'])
        try:
            self.query.command('servergroupaddclient', sgid=group_id, cldbid=db_id)
        except QueryError as error:
            if error.error_id != ERR_DUPLICATE:
                raise
        return {'cldbid': db_id}

    def revoke_guild(self, payload):
        group_id = self.guild_group_id()
        try:
            db_id = self.client_db_id(payload['uid'])
            self.query.command('servergroupdelclient', sgid=group_id, cldbid=db_id)
        except (TaskError, QueryError):
            pass  # Клиента нет или он уже не в группе — снимать нечего
        return {}

    def create_room(self, payload):
        channels = self.query.command('channellist')
        parent_path = self.config.get('rooms_parent', 'Гильдия / Комнаты членов гильдии')
        parent = find_channel(channels, parent_path)
        if parent is None:
            raise TaskError(f'На сервере нет раздела «{parent_path}»')
        name = payload['name']
        if any(c['pid'] == parent and c['channel_name'] == name for c in channels):
            raise TaskError(f'Комната «{name}» уже есть — выберите другое название')

        try:
            cid = self.query.command('channelcreate', channel_name=name, cpid=parent, channel_flag_permanent=1)[0]['cid']
        except QueryError as error:
            if error.error_id == ERR_NAME_IN_USE:
                raise TaskError(f'Комната «{name}» уже есть — выберите другое название') from None
            raise
        # Комната внутри раздела гильдии — тоже только для гильдии.
        self.query.command('channeladdperm', cid=cid, items=guild_channel_perms(self.config['guild_power']))

        result = {'cid': int(cid), 'owner_admin': False}
        try:
            db_id = self.client_db_id(payload['owner_uid'])
            admin_group = next((g['cgid'] for g in self.query.command('channelgrouplist')
                                if g['name'] == 'Channel Admin' and g.get('type') == '1'), None)
            if admin_group:
                self.query.command('setclientchannelgroup', cgid=admin_group, cid=cid, cldbid=db_id)
                result['owner_admin'] = True
        except TaskError:
            pass  # Владелец ещё не заходил — комната создана, админом его можно сделать позже
        return result

    def delete_room(self, payload):
        try:
            self.query.command('channeldelete', cid=payload['cid'], force=1)
        except QueryError as error:
            if error.error_id != ERR_INVALID_CHANNEL:
                raise
        return {}

    def install_license(self, payload):
        """Кладёт файл лицензии в данные TeamSpeak и перезапускает сервер.

        Контейнер teamspeak перезапускается Docker'ом (restart: unless-stopped) после
        serverprocessstop. Если с новой лицензией сервер не поднялся — возвращается старая.
        """
        data = self.api.license()
        if not data:
            raise TaskError('На сайте нет файла лицензии')
        target = self.ts_data_dir / 'licensekey.dat'
        backup = self.ts_data_dir / 'licensekey.dat.bak'
        if target.exists():
            target.replace(backup)
        temporary = self.ts_data_dir / 'licensekey.dat.new'
        temporary.write_bytes(data)
        os.chmod(temporary, 0o644)
        temporary.replace(target)
        self.log('Лицензия записана, перезапускаю сервер TeamSpeak...')

        try:
            self.query.command('serverprocessstop', reasonmsg='Установка лицензии, сервер вернётся через минуту')
        except (QueryError, OSError):
            pass  # Сервер закрывает соединение, не дожидаясь ответа
        self.query.close()
        self.query = None
        time.sleep(10)

        deadline = time.time() + RESTART_WAIT
        while time.time() < deadline:
            try:
                self.ensure_connected()
                break
            except (ConnectionError, OSError, QueryError):
                time.sleep(5)
        else:
            if backup.exists():
                backup.replace(target)
                raise TaskError('Сервер TeamSpeak не запустился с новой лицензией — возвращена прежняя. '
                                'Проверьте файл лицензии и логи: docker compose logs teamspeak')
            target.unlink(missing_ok=True)
            raise TaskError('Сервер TeamSpeak не запустился с новой лицензией — она удалена. '
                            'Проверьте файл и логи: docker compose logs teamspeak')

        result = {}
        if payload.get('max_clients'):
            self.query.command('serveredit', virtualserver_maxclients=payload['max_clients'])
            result['max_clients'] = payload['max_clients']
        result['max_clients_now'] = self.query.command('serverinfo')[0].get('virtualserver_maxclients')
        return result

    def run_task(self, task):
        handler = self.handlers.get(task['type'])
        if not handler:
            return False, {}, f'Неизвестная задача: {task["type"]}'
        try:
            return True, handler(task.get('payload') or {}), ''
        except TaskError as error:
            return False, {}, str(error)
        except QueryError as error:
            return False, {}, f'Ошибка TeamSpeak: {error}'

    # ----- присутствие -----

    def presence_snapshot(self):
        paths = channel_paths(self.query.command('channellist'))
        return [{'uid': c['client_unique_identifier'], 'path': paths.get(c['cid'], [])}
                for c in self.online_clients()]

    # ----- цикл -----

    def tick(self, now, state):
        """Один шаг: выполнить задачи и при необходимости отправить присутствие."""
        for task in state.get('tasks', []):
            ok, data, error = self.run_task(task)
            self.log(f'Задача #{task["id"]} {task["type"]}: {"готово" if ok else "ошибка — " + error}')
            self.api.task_result(task['id'], ok, data, error)

        if state.get('track_presence') and now - self.last_presence >= PRESENCE_INTERVAL:
            self.api.presence(self.presence_snapshot())
            self.last_presence = now

        if now - self.last_keepalive >= KEEPALIVE_INTERVAL:
            self.query.command('whoami')
            self.last_keepalive = now

    def run_forever(self):
        api_error = None
        while True:
            try:
                self.ensure_connected()
                state = self.api.state()
                if api_error:
                    self.log('Связь с сайтом восстановлена')
                    api_error = None
                self.tick(time.time(), state)
            except SiteApiError as error:
                if str(error) != api_error:
                    self.log(f'Нет связи с сайтом: {error}')
                    api_error = str(error)
            except (ConnectionError, OSError, QueryError) as error:
                self.log(f'Потеряно соединение с TeamSpeak ({error}) — переподключаюсь')
                self.query = None
                time.sleep(5)
            time.sleep(POLL_INTERVAL)
