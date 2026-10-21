"""Начальная настройка сервера TeamSpeak по channels.json. Выполняется при каждом старте бота.

- группа по умолчанию, в которую TeamSpeak кладёт каждого посетителя (Guest), переименовывается
  (default_group_name);
- группой гильдии становится стандартная группа Normal (guild_group_source) — её TeamSpeak
  автоматически не выдаёт, и у неё уже есть права на разговор и т. п.; сила доступа — guild_power;
- создаются недостающие каналы; на каналах guild_only закрывается вход, подписка и описание;
- пока у сервера нет администратора, печатается одноразовый ключ Server Admin.

Повторный запуск безопасен: существующее не пересоздаётся.

Ограничение TeamSpeak 3: полностью скрыть канал нельзя — названия комнат гильдии видны всем.
"""
import json

# Права, которые закрывают канал для всех, кроме группы гильдии (и администраторов).
GUILD_CHANNEL_PERMS = ['i_channel_needed_join_power', 'i_channel_needed_subscribe_power',
                       'i_channel_needed_description_view_power']
GUILD_GROUP_PERMS = ['i_channel_join_power', 'i_channel_subscribe_power', 'i_channel_description_view_power']


def load_config(path):
    with open(path, encoding='utf-8') as file:
        config = json.load(file)
    config['guild_power'] = int(config.get('guild_power', 60))
    if config['guild_power'] <= 0:
        raise SystemExit('guild_power в channels.json должен быть больше 0')
    return config


def expand(nodes):
    """Раскрывает count: {"name": "Пати {n}", "count": 3} -> Пати 1, Пати 2, Пати 3."""
    result = []
    for node in nodes:
        if 'count' in node:
            for number in range(1, node['count'] + 1):
                copy = {key: value for key, value in node.items() if key != 'count'}
                copy['name'] = node['name'].replace('{n}', str(number))
                result.append(copy)
        else:
            result.append(node)
    return result


def guild_channel_perms(power):
    return [{'permsid': perm, 'permvalue': power} for perm in GUILD_CHANNEL_PERMS]


class Setup:
    def __init__(self, query, config, log=print):
        self.query = query
        self.config = config
        self.power = config['guild_power']
        self.log = log
        self.created = 0
        self.channels = query.command('channellist')

    # ----- группы -----

    def server_groups(self):
        return [g for g in self.query.command('servergrouplist') if g.get('type') == '1']

    def default_group_id(self):
        return self.query.command('serverinfo')[0].get('virtualserver_default_server_group')

    def join_power(self, group_id):
        perms = self.query.list('servergrouppermlist', '-permsid', sgid=group_id)
        return int(next((p['permvalue'] for p in perms if p.get('permsid') == 'i_channel_join_power'), 0))

    def rename_default_group(self):
        name = self.config.get('default_group_name')
        if not name:
            return
        default_id = self.default_group_id()
        group = next((g for g in self.server_groups() if g['sgid'] == default_id), None)
        if group and group['name'] != name:
            self.query.command('servergrouprename', sgid=default_id, name=name)
            self.log(f'Группа по умолчанию «{group["name"]}» переименована в «{name}»')

    def check_guild_power(self):
        """Порог доступа к комнатам гильдии должен быть выше силы входа группы посетителей."""
        visitors = self.join_power(self.default_group_id())
        if self.power <= visitors:
            raise SystemExit(f'guild_power в channels.json ({self.power}) должен быть больше силы входа группы '
                             f'посетителей ({visitors}), иначе в комнаты гильдии смогут зайти все')

    def ensure_guild_group(self):
        """Группа гильдии — переименованная стандартная группа Normal (guild_group_source).

        Если группа гильдии уже создана отдельно (так делали ранние версии бота) и в ней никого нет —
        она удаляется, а Normal переименовывается. Если в ней есть люди — ничего не удаляется.
        """
        name = self.config['guild_group']
        source_name = self.config.get('guild_group_source', 'Normal')
        groups = self.server_groups()
        group = next((g for g in groups if g['name'] == name), None)
        source = next((g for g in groups if g['name'] == source_name), None) if source_name != name else None

        if group and source:
            if not self.query.list('servergroupclientlist', sgid=group['sgid']):
                self.query.command('servergroupdel', sgid=group['sgid'], force=1)
                self.log(f'Удалена пустая группа «{name}» — вместо неё будет переименована «{source_name}»')
                group = None
            else:
                self.log(f'Подсказка: на сервере есть и «{name}», и «{source_name}». Бот выдаёт «{name}»; '
                         f'«{source_name}» можно удалить вручную, если она не нужна')

        if group:
            group_id = group['sgid']
        elif source:
            group_id = source['sgid']
            self.query.command('servergrouprename', sgid=group_id, name=name)
            self.log(f'Группа «{source_name}» переименована в «{name}»')
        else:
            group_id = self.query.command('servergroupadd', name=name)[0]['sgid']
            self.log(f'Создана группа «{name}»')
        self.query.command('servergroupaddperm', sgid=group_id, items=[
            {'permsid': perm, 'permvalue': self.power, 'permnegated': 0, 'permskip': 0} for perm in GUILD_GROUP_PERMS
        ])
        return group_id

    # ----- каналы -----

    def find_child(self, parent_id, name):
        for channel in self.channels:
            if channel['pid'] == str(parent_id) and channel['channel_name'] == name:
                return channel['cid']
        return None

    def ensure_channel(self, node, parent_id, after_id, guild_only):
        name = node['name']
        channel_id = self.find_child(parent_id, name)

        if channel_id is None and node.get('default'):
            # Канал по умолчанию уже есть («Default Channel») — переименовываем его.
            default = next((c for c in self.channels if c['pid'] == '0' and 'Default Channel' in c['channel_name']), None)
            if default:
                self.query.command('channeledit', cid=default['cid'], channel_name=name)
                default['channel_name'] = name
                channel_id = default['cid']
                self.log(f'Канал по умолчанию переименован в «{name}»')

        if channel_id is None:
            params = {'channel_name': name, 'channel_flag_permanent': 1, 'cpid': parent_id}
            if after_id:
                params['channel_order'] = after_id
            if node.get('description'):
                params['channel_description'] = node['description']
            channel_id = self.query.command('channelcreate', **params)[0]['cid']
            self.channels.append({'cid': channel_id, 'pid': str(parent_id), 'channel_name': name})
            self.created += 1
            self.log(f'Создан канал «{name}»')

        guild_only = guild_only or node.get('guild_only', False)
        if guild_only:
            self.query.command('channeladdperm', cid=channel_id, items=guild_channel_perms(self.power))

        previous = None
        for child in expand(node.get('children', [])):
            previous = self.ensure_channel(child, channel_id, previous, guild_only)
        return channel_id

    # ----- администратор -----

    def admin_token(self):
        """Неиспользованный ключ Server Admin, пока у сервера нет администратора (иначе None)."""
        admin = next((g for g in self.server_groups() if g['name'] == 'Server Admin'), None)
        if not admin or self.query.list('servergroupclientlist', sgid=admin['sgid']):
            return None
        tokens = self.query.list('tokenlist')
        token = next((t['token'] for t in tokens if t.get('token_id1') == admin['sgid']), None)
        if not token:
            token = self.query.command('tokenadd', tokentype=0, tokenid1=admin['sgid'], tokenid2=0)[0]['token']
        return token

    def run(self):
        self.check_guild_power()
        self.rename_default_group()
        self.ensure_guild_group()
        previous = None
        for node in expand(self.config['channels']):
            previous = self.ensure_channel(node, 0, previous, False)

        token = self.admin_token()
        if token:
            self.log('')
            self.log('Ключ администратора TeamSpeak — введите его в клиенте: Права → Использовать ключ привилегий')
            self.log(f'    {token}')
            self.log('')
        self.log(f'Настройка TeamSpeak: создано каналов — {self.created}, структура соответствует channels.json')
