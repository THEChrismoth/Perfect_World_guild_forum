"""Тесты бота без настоящего TeamSpeak: FakeQuery хранит каналы, группы и клиентов в памяти.

Запуск из папки tsbot: python -m unittest discover -s tests -t .
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tsbot import bot as bot_module
from tsbot.bot import Bot
from tsbot.query import QueryError, build_command, escape, parse_item, unescape
from tsbot.setup import Setup
from tsbot.tree import channel_paths, find_channel

UID = 'A' * 27 + '='

CONFIG = {
    'default_group_name': 'Гость',
    'guild_group': 'Член гильдии',
    'guild_power': 60,
    'rooms_parent': 'Гильдия / Комнаты членов гильдии',
    'channels': [
        {'name': 'Гостиная', 'default': True, 'children': [{'name': 'Гостевая {n}', 'count': 2}]},
        {'name': 'Гильдия', 'guild_only': True, 'children': [
            {'name': 'МТВ / ГВГ', 'children': [{'name': 'Пати {n}', 'count': 2}]},
            {'name': 'Комнаты членов гильдии'},
        ]},
    ],
}


class FakeQuery:
    """Минимальная модель сервера TeamSpeak для команд, которые использует бот."""

    def __init__(self):
        self.channels = [{'cid': '1', 'pid': '0', 'channel_name': 'Default Channel'}]
        self.groups = [
            {'sgid': '6', 'name': 'Server Admin', 'type': '1'},
            {'sgid': '7', 'name': 'Normal', 'type': '1'},
            # Группа по умолчанию — Guest (sgid 8), как на настоящем сервере TeamSpeak 3.
            {'sgid': '8', 'name': 'Guest', 'type': '1'},
            {'sgid': '1', 'name': 'Guest Server Query', 'type': '2'},
        ]
        self.group_powers = {'6': 75, '7': 50, '8': 0}
        self.group_members = {}
        self.channel_perms = {}
        self.channel_groups_set = []
        self.known_clients = {UID: '15'}
        self.online = []
        self.messages = []
        self.pokes = []
        self.commands = []
        self.closed = False
        self.next_id = 100

    def _id(self):
        self.next_id += 1
        return str(self.next_id)

    def close(self):
        self.closed = True

    def list(self, cmd, *flags, **params):
        try:
            return self.command(cmd, *flags, **params)
        except QueryError as error:
            if error.error_id == 1281:
                return []
            raise

    def command(self, cmd, *flags, items=None, **params):
        self.commands.append(cmd)
        if cmd == 'channellist':
            return [dict(c) for c in self.channels]
        if cmd == 'servergrouplist':
            return [dict(g) for g in self.groups]
        if cmd == 'serverinfo':
            return [{'virtualserver_default_server_group': '8', 'virtualserver_maxclients': '32'}]
        if cmd == 'servergrouppermlist':
            power = self.group_powers.get(params['sgid'])
            if not power:
                raise QueryError(1281, 'database empty result set')
            return [{'permsid': 'i_channel_join_power', 'permvalue': str(power)}]
        if cmd == 'servergroupdel':
            self.groups = [g for g in self.groups if g['sgid'] != params['sgid']]
            return []
        if cmd == 'servergrouprename':
            next(g for g in self.groups if g['sgid'] == params['sgid'])['name'] = params['name']
            return []
        if cmd == 'servergroupadd':
            sgid = self._id()
            self.groups.append({'sgid': sgid, 'name': params['name'], 'type': '1'})
            return [{'sgid': sgid}]
        if cmd in ('servergroupaddperm', 'channeladdperm', 'clientupdate', 'whoami', 'serveredit', 'serverprocessstop'):
            if cmd == 'channeladdperm':
                self.channel_perms[str(params['cid'])] = {i['permsid']: i['permvalue'] for i in items}
            return []
        if cmd == 'channeledit':
            next(c for c in self.channels if c['cid'] == str(params['cid']))['channel_name'] = params['channel_name']
            return []
        if cmd == 'channelcreate':
            parent = str(params.get('cpid', 0))
            if any(c['pid'] == parent and c['channel_name'] == params['channel_name'] for c in self.channels):
                raise QueryError(771, 'channel name is already in use')
            cid = self._id()
            self.channels.append({'cid': cid, 'pid': parent, 'channel_name': params['channel_name']})
            return [{'cid': cid}]
        if cmd == 'channeldelete':
            before = len(self.channels)
            self.channels = [c for c in self.channels if c['cid'] != str(params['cid'])]
            if len(self.channels) == before:
                raise QueryError(768, 'invalid channelID')
            return []
        if cmd == 'servergroupclientlist':
            members = self.group_members.get(params['sgid'], set())
            if not members:
                raise QueryError(1281, 'database empty result set')
            return [{'cldbid': m} for m in members]
        if cmd == 'tokenlist':
            raise QueryError(1281, 'database empty result set')
        if cmd == 'tokenadd':
            return [{'token': 'ADMIN-TOKEN'}]
        if cmd == 'clientgetdbidfromuid':
            if params['cluid'] not in self.known_clients:
                raise QueryError(512, 'invalid clientID')
            return [{'cldbid': self.known_clients[params['cluid']]}]
        if cmd == 'servergroupaddclient':
            members = self.group_members.setdefault(params['sgid'], set())
            if params['cldbid'] in members:
                raise QueryError(2561, 'duplicate entry')
            members.add(params['cldbid'])
            return []
        if cmd == 'servergroupdelclient':
            self.group_members.get(params['sgid'], set()).discard(params['cldbid'])
            return []
        if cmd == 'clientlist':
            return [dict(c) for c in self.online]
        if cmd == 'sendtextmessage':
            self.messages.append((params['target'], params['msg']))
            return []
        if cmd == 'clientpoke':
            self.pokes.append(params['clid'])
            return []
        if cmd == 'channelgrouplist':
            return [{'cgid': '5', 'name': 'Channel Admin', 'type': '1'}]
        if cmd == 'setclientchannelgroup':
            self.channel_groups_set.append((params['cgid'], str(params['cid']), params['cldbid']))
            return []
        raise AssertionError(f'Неожиданная команда {cmd} {params}')


class FakeApi:
    def __init__(self):
        self.results = []
        self.presence_calls = []
        self.license_data = b'LICENSE'

    def task_result(self, task_id, ok, data=None, error=''):
        self.results.append((task_id, ok, data, error))

    def presence(self, clients):
        self.presence_calls.append(clients)

    def license(self):
        return self.license_data


def prepared_server():
    query = FakeQuery()
    Setup(query, CONFIG, log=lambda *_: None).run()
    return query


class EscapingTests(unittest.TestCase):
    def test_round_trip(self):
        text = 'МТВ / ГВГ | пати\\1'
        self.assertEqual(unescape(escape(text)), text)
        self.assertEqual(escape('a b/c'), 'a\\sb\\/c')

    def test_build_with_items(self):
        line = build_command('channeladdperm', items=[{'permsid': 'a', 'permvalue': 60}, {'permsid': 'b', 'permvalue': 60}], cid=5)
        self.assertEqual(line, 'channeladdperm cid=5 permsid=a permvalue=60|permsid=b permvalue=60')

    def test_parse(self):
        self.assertEqual(parse_item('cid=1 channel_name=МТВ\\s\\/\\sГВГ'), {'cid': '1', 'channel_name': 'МТВ / ГВГ'})


class SetupTests(unittest.TestCase):
    def test_structure_groups_and_permissions(self):
        query = prepared_server()
        paths = {' / '.join(p) for p in channel_paths(query.channels).values()}

        self.assertIn('Гостиная / Гостевая 2', paths)
        self.assertIn('Гильдия / МТВ / ГВГ / Пати 2', paths)
        self.assertIn('Гильдия / Комнаты членов гильдии', paths)
        names = {g['name'] for g in query.groups}
        self.assertIn('Гость', names)            # Guest — группа посетителей по умолчанию
        self.assertIn('Член гильдии', names)     # Переименованная Normal
        self.assertNotIn('Normal', names)
        self.assertEqual(next(g['sgid'] for g in query.groups if g['name'] == 'Член гильдии'), '7')
        guild_cid = find_channel(query.channels, 'Гильдия')
        self.assertEqual(query.channel_perms[guild_cid]['i_channel_needed_join_power'], 60)
        guest_cid = find_channel(query.channels, 'Гостиная / Гостевая 1')
        self.assertNotIn(guest_cid, query.channel_perms)

    def test_idempotent(self):
        query = prepared_server()
        count = len(query.channels)
        Setup(query, CONFIG, log=lambda *_: None).run()
        self.assertEqual(len(query.channels), count)
        self.assertEqual(sum(g['name'] == 'Член гильдии' for g in query.groups), 1)

    def test_admin_token_only_without_admin(self):
        query = prepared_server()
        setup = Setup(query, CONFIG, log=lambda *_: None)
        self.assertEqual(setup.admin_token(), 'ADMIN-TOKEN')
        query.group_members['6'] = {'1'}
        self.assertIsNone(setup.admin_token())


class GuildGroupMergeTests(unittest.TestCase):
    def test_empty_separate_group_replaced_by_normal(self):
        query = FakeQuery()
        query.groups.append({'sgid': '20', 'name': 'Член гильдии', 'type': '1'})

        Setup(query, CONFIG, log=lambda *_: None).run()

        guild = [g for g in query.groups if g['name'] == 'Член гильдии']
        self.assertEqual([g['sgid'] for g in guild], ['7'])

    def test_group_with_members_kept(self):
        query = FakeQuery()
        query.groups.append({'sgid': '20', 'name': 'Член гильдии', 'type': '1'})
        query.group_members['20'] = {'15'}

        Setup(query, CONFIG, log=lambda *_: None).run()

        self.assertIn('20', [g['sgid'] for g in query.groups if g['name'] == 'Член гильдии'])
        self.assertIn('Normal', [g['name'] for g in query.groups])

    def test_power_must_exceed_visitors(self):
        query = FakeQuery()
        query.group_powers['8'] = 70
        with self.assertRaises(SystemExit):
            Setup(query, CONFIG, log=lambda *_: None).run()


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.query = prepared_server()
        self.api = FakeApi()
        self.bot = Bot(lambda: self.query, self.api, CONFIG, log=lambda *_: None)
        self.bot.query = self.query
        self.guild_sgid = next(g['sgid'] for g in self.query.groups if g['name'] == 'Член гильдии')

    def run_task(self, task_type, **payload):
        return self.bot.run_task({'id': 1, 'type': task_type, 'payload': payload})

    def test_verify_link_offline(self):
        ok, _, error = self.run_task('verify_link', uid=UID, username='Аквилон', url='https://site/confirm/x/')
        self.assertFalse(ok)
        self.assertIn('не подключены', error)

    def test_verify_link_sends_message_and_poke(self):
        self.query.online = [{'clid': '3', 'cid': '1', 'client_type': '0', 'client_unique_identifier': UID}]
        ok, data, _ = self.run_task('verify_link', uid=UID, username='Аквилон', url='https://site/confirm/x/')
        self.assertTrue(ok)
        self.assertEqual(self.query.pokes, ['3'])
        self.assertIn('[URL]https://site/confirm/x/[/URL]', self.query.messages[0][1])

    def test_grant_twice_and_revoke(self):
        self.assertTrue(self.run_task('grant_guild', uid=UID)[0])
        self.assertTrue(self.run_task('grant_guild', uid=UID)[0])  # Повторно — не ошибка
        self.assertEqual(self.query.group_members[self.guild_sgid], {'15'})
        self.assertTrue(self.run_task('revoke_guild', uid=UID)[0])
        self.assertEqual(self.query.group_members[self.guild_sgid], set())

    def test_grant_unknown_client(self):
        ok, _, error = self.run_task('grant_guild', uid='Z' * 27 + '=')
        self.assertFalse(ok)
        self.assertIn('ещё не заходил', error)

    def test_create_and_delete_room(self):
        ok, data, _ = self.run_task('create_room', name='Комната Аквилона', owner_uid=UID)
        self.assertTrue(ok)
        cid = str(data['cid'])
        parent = find_channel(self.query.channels, 'Гильдия / Комнаты членов гильдии')
        self.assertEqual(next(c for c in self.query.channels if c['cid'] == cid)['pid'], parent)
        self.assertEqual(self.query.channel_perms[cid]['i_channel_needed_join_power'], 60)
        self.assertEqual(self.query.channel_groups_set, [('5', cid, '15')])

        ok, _, error = self.run_task('create_room', name='Комната Аквилона', owner_uid=UID)
        self.assertFalse(ok)
        self.assertIn('уже есть', error)

        self.assertTrue(self.run_task('delete_room', cid=int(cid))[0])
        self.assertTrue(self.run_task('delete_room', cid=int(cid))[0])  # Уже удалена — не ошибка

    def test_room_for_owner_who_never_connected(self):
        ok, data, _ = self.run_task('create_room', name='Комната', owner_uid='Z' * 27 + '=')
        self.assertTrue(ok)
        self.assertFalse(data['owner_admin'])

    def test_install_license(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(bot_module.time, 'sleep'):
            self.bot.ts_data_dir = Path(tmp)
            (Path(tmp) / 'licensekey.dat').write_bytes(b'OLD')
            ok, data, error = self.run_task('install_license', max_clients=64)
            self.assertTrue(ok, error)
            self.assertEqual((Path(tmp) / 'licensekey.dat').read_bytes(), b'LICENSE')
            self.assertEqual((Path(tmp) / 'licensekey.dat.bak').read_bytes(), b'OLD')
            self.assertIn('serverprocessstop', self.query.commands)
            self.assertEqual(data['max_clients'], 64)

    def test_install_license_rolls_back_when_server_does_not_start(self):
        def never_starts():
            raise ConnectionError('нет сервера')

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(bot_module.time, 'sleep'), \
                mock.patch.object(bot_module, 'RESTART_WAIT', 0):
            self.bot.connect_query = never_starts
            self.bot.ts_data_dir = Path(tmp)
            (Path(tmp) / 'licensekey.dat').write_bytes(b'OLD')
            ok, _, error = self.run_task('install_license')
            self.assertFalse(ok)
            self.assertIn('возвращена прежняя', error)
            self.assertEqual((Path(tmp) / 'licensekey.dat').read_bytes(), b'OLD')

    def test_tick_reports_results_and_presence(self):
        self.query.online = [{'clid': '3', 'cid': find_channel(self.query.channels, 'Гильдия / МТВ / ГВГ / Пати 1'),
                              'client_type': '0', 'client_unique_identifier': UID, 'client_nickname': 'Аквилон'},
                             {'clid': '4', 'cid': '1', 'client_type': '1', 'client_unique_identifier': 'serveradmin'}]
        self.bot.tick(1000, {'tasks': [{'id': 7, 'type': 'grant_guild', 'payload': {'uid': UID}}], 'track_presence': True})

        self.assertEqual(self.api.results[0][:2], (7, True))
        self.assertEqual(self.api.presence_calls, [[{'uid': UID, 'path': ['Гильдия', 'МТВ / ГВГ', 'Пати 1']}]])
        # Чаще раза в минуту не отправляется, а вне ивента — вообще.
        self.bot.tick(1010, {'tasks': [], 'track_presence': True})
        self.assertEqual(len(self.api.presence_calls), 1)
        self.bot.tick(2000, {'tasks': [], 'track_presence': False})
        self.assertEqual(len(self.api.presence_calls), 1)

    def test_unknown_task(self):
        ok, _, error = self.run_task('make_coffee')
        self.assertFalse(ok)
        self.assertIn('Неизвестная', error)


if __name__ == '__main__':
    unittest.main()
