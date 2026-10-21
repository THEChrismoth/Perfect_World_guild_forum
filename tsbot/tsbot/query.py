"""Клиент ServerQuery TeamSpeak 3 (raw-протокол, порт 10011)."""
import socket
import time

# Защита TeamSpeak от флуда пропускает около 10 команд за 3 секунды.
COMMAND_DELAY = 0.35
FLOOD_ERROR = 524
FLOOD_RETRIES = 5
EMPTY_RESULT = 1281

ESCAPES = [('\\', '\\\\'), ('/', '\\/'), (' ', '\\s'), ('|', '\\p'),
           ('\a', '\\a'), ('\b', '\\b'), ('\f', '\\f'), ('\n', '\\n'), ('\r', '\\r'), ('\t', '\\t'), ('\v', '\\v')]
_UNESCAPE = {escaped[1]: raw for raw, escaped in ESCAPES}


def escape(value):
    value = str(value)
    for raw, escaped in ESCAPES:
        value = value.replace(raw, escaped)
    return value


def unescape(value):
    result, index = [], 0
    while index < len(value):
        if value[index] == '\\' and index + 1 < len(value):
            result.append(_UNESCAPE.get(value[index + 1], value[index + 1]))
            index += 2
        else:
            result.append(value[index])
            index += 1
    return ''.join(result)


def parse_item(text):
    item = {}
    for pair in text.split(' '):
        key, _, value = pair.partition('=')
        item[key] = unescape(value)
    return item


def build_command(cmd, flags=(), items=None, **params):
    parts = [cmd]
    parts += [f'{key}={escape(value)}' for key, value in params.items()]
    if items:
        parts.append('|'.join(' '.join(f'{key}={escape(value)}' for key, value in item.items()) for item in items))
    parts += list(flags)
    return ' '.join(parts)


class QueryError(Exception):
    def __init__(self, error_id, message):
        super().__init__(f'{message} (код {error_id})')
        self.error_id = error_id
        self.message = message


class ServerQuery:
    def __init__(self, host, port, timeout=15, delay=COMMAND_DELAY):
        self.delay = delay
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.buffer = b''
        # Приветствие: «TS3» и строка «Welcome to the TeamSpeak 3 ServerQuery interface...».
        self._read_line()
        self._read_line()

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def _read_line(self):
        while b'\n' not in self.buffer:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError('Сервер TeamSpeak закрыл соединение')
            self.buffer += chunk
        line, self.buffer = self.buffer.split(b'\n', 1)
        return line.decode('utf-8').strip('\r')

    def _read_response(self):
        data = []
        while True:
            line = self._read_line()
            if not line:
                continue
            if line.startswith('error '):
                fields = parse_item(line[len('error '):])
                error_id = int(fields.get('id', 0))
                if error_id != 0:
                    raise QueryError(error_id, fields.get('msg', 'ошибка'))
                return data
            if line.startswith('notify'):
                continue  # Уведомления о событиях бот не подписывает, но на всякий случай пропускаем
            data.extend(parse_item(item) for item in line.split('|'))

    def command(self, cmd, *flags, items=None, **params):
        """Выполняет команду и возвращает строки результата списком словарей.

        items — несколько наборов параметров в одной команде (через «|»).
        При ответе «client is flooding» ждёт и повторяет.
        """
        line = build_command(cmd, flags, items, **params) + '\n'
        for attempt in range(FLOOD_RETRIES + 1):
            self.sock.sendall(line.encode('utf-8'))
            time.sleep(self.delay)
            try:
                return self._read_response()
            except QueryError as error:
                if error.error_id != FLOOD_ERROR or attempt == FLOOD_RETRIES:
                    raise
                time.sleep(3.5)

    def list(self, cmd, *flags, **params):
        """Как command, но пустой результат (ошибка 1281) превращается в []."""
        try:
            return self.command(cmd, *flags, **params)
        except QueryError as error:
            if error.error_id != EMPTY_RESULT:
                raise
            return []


def connect(host, port, password, nickname, log=print, wait_seconds=120):
    """Подключается (дожидаясь запуска сервера), входит как serveradmin и выбирает сервер 1."""
    deadline = time.time() + wait_seconds
    while True:
        try:
            query = ServerQuery(host, port)
            break
        except OSError as error:
            if time.time() > deadline:
                raise ConnectionError(f'Не удалось подключиться к {host}:{port}: {error}') from None
            log('Жду запуска сервера TeamSpeak...')
            time.sleep(3)
    query.command('login', client_login_name='serveradmin', client_login_password=password)
    query.command('use', sid=1)
    try:
        query.command('clientupdate', client_nickname=nickname)
    except QueryError:
        pass  # Ник занят — не страшно
    return query
