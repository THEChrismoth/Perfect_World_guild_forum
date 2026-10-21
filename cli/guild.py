#!/usr/bin/env python3
"""Управление сайтом гильдии на сервере: установка, запуск, обновление, логи, резервные копии.

Работает из любой папки — папку сайта находит по своему расположению.
Только стандартная библиотека и Python 3.8+, чтобы запускаться системным Python сервера.

Первая установка: install.sh в корне репозитория (он вызывает guild setup).
Установить команду guild в систему: sudo python3 cli/guild.py install
Список команд: guild help
"""

import argparse
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Настоящий путь к скрипту, даже если guild запущен через ссылку из /usr/local/bin.
SCRIPT = Path(__file__).resolve()
ROOT = SCRIPT.parent.parent
ENV_FILE = ROOT / '.env'
# Данные незавершенной установки: по ним guild setup продолжает с места остановки.
SETUP_STATE = ROOT / '.guild-setup.json'
LINK = Path('/usr/local/bin/guild')
LOG = Path('/var/log/guild-install.log')

TS_PORT = 9987
# Порты, которые открывают контейнеры caddy и teamspeak.
PORTS = {('tcp', 80), ('tcp', 443), ('udp', 443), ('udp', TS_PORT), ('tcp', 30033)}
# Публичные DNS: проверяем записи так, как их видит интернет, а не кеш сервера и /etc/hosts.
RESOLVERS = ('1.1.1.1', '8.8.8.8')
RESERVED_LOGINS = {'admin', 'administrator', 'root', 'guild'}

if sys.stdout.isatty():
    BOLD, GREEN, YELLOW, RED, RESET = '\033[1m', '\033[32m', '\033[33m', '\033[31m', '\033[0m'
else:
    BOLD = GREEN = YELLOW = RED = RESET = ''
OK, FAIL = f'{GREEN}✓{RESET}', f'{RED}✗{RESET}'


class GuildError(Exception):
    """Ошибка, после которой команда завершается с понятным сообщением."""


def info(message):
    """Печатает шаг выполнения команды."""
    print(f'{GREEN}==>{RESET} {BOLD}{message}{RESET}', flush=True)


def warn(message):
    """Печатает предупреждение в stderr."""
    sys.stdout.flush()  # Чтобы предупреждение не обогнало уже напечатанное
    print(f'{YELLOW}{message}{RESET}', file=sys.stderr, flush=True)


def run(*args, check=True, capture=False, input=None):
    """Запускает программу в папке сайта и возвращает CompletedProcess.

    Аргументы:
        check: при ненулевом коде возврата завершить guild с тем же кодом.
        capture: вернуть вывод программы, а не печатать его.
        input: текст, который передается программе на stdin.
    """
    result = subprocess.run(args, cwd=ROOT, capture_output=capture, input=input, encoding='utf-8', errors='replace')
    if check and result.returncode != 0:
        if capture and result.stderr:
            print(result.stderr, end='', file=sys.stderr)
        raise SystemExit(result.returncode)
    return result


def compose(*args, **kwargs):
    """Запускает docker compose с аргументами."""
    return run('docker', 'compose', *args, **kwargs)


def git(*args, **kwargs):
    """Запускает git в папке сайта."""
    return run('git', '-C', str(ROOT), *args, **kwargs)


def manage(*args, capture=False, check=True):
    """Запускает manage.py в контейнере web."""
    # Без терминала (например, из cron) docker compose exec нужно запускать с -T.
    tty = [] if sys.stdin.isatty() and not capture else ['-T']
    return compose('exec', *tty, 'web', 'python', 'manage.py', *args, capture=capture, check=check)


def version_string():
    """Возвращает версию сайта: тег релиза (или коммит) и дату."""
    version = git('describe', '--tags', '--always', check=False, capture=True).stdout.strip()
    date = git('log', '-1', '--format=%cd', '--date=format:%d.%m.%Y', check=False, capture=True).stdout.strip()
    return f'{version} от {date}' if version else 'неизвестна'


def read_env():
    """Возвращает значения из .env в виде словаря."""
    values = {}
    for line in ENV_FILE.read_text(encoding='utf-8').splitlines():
        key, sep, value = line.partition('=')
        if sep and not key.lstrip().startswith('#'):
            values[key.strip()] = value.strip()
    return values


def site_domains():
    """Возвращает домены сайта из DOMAIN в .env."""
    return [d.strip() for d in read_env().get('DOMAIN', '').split(',') if d.strip()]


def docker_ready():
    """Проверяет, что установлены Docker и docker compose."""
    return bool(shutil.which('docker')) and run('docker', 'compose', 'version', check=False, capture=True).returncode == 0


def require_setup():
    """Проверяет, что установлен Docker и создан .env."""
    if not shutil.which('docker'):
        raise GuildError('Docker не установлен. Установите сайт командой из README или: curl -fsSL https://get.docker.com | sh')
    if not docker_ready():
        raise GuildError('Не найден docker compose. Обновите Docker.')
    if not ENV_FILE.exists():
        raise GuildError(f'Нет файла {ENV_FILE}. Запустите установку: sudo guild setup')


def require_root(command):
    """Проверяет, что команда запущена от root."""
    if os.geteuid() != 0:
        raise GuildError(f'Команде нужны права root. Запустите: sudo python3 {SCRIPT} {command}')


def find_ts_key():
    """Возвращает ключ администратора TeamSpeak из логов бота или None."""
    lines = compose('logs', '--no-log-prefix', 'tsbot', check=False, capture=True).stdout.splitlines()
    # Бот печатает ключ строкой ниже заголовка (tsbot/tsbot/setup.py).
    keys = [lines[i + 1].strip() for i, line in enumerate(lines[:-1]) if 'Ключ администратора TeamSpeak' in line]
    return keys[-1] if keys else None


def ts_address():
    """Возвращает адрес TeamSpeak из настроек сайта."""
    result = manage('ts_address', capture=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else ''


# Обычные команды. Каждая получает разобранные аргументы argparse.

def cmd_start(args):
    """Запускает сайт или применяет изменения .env."""
    info('Запускаю сайт')
    compose('up', '-d')


def cmd_stop(args):
    """Останавливает сайт."""
    info('Останавливаю сайт')
    compose('down')


def cmd_restart(args):
    """Перезапускает все сервисы или выбранные."""
    info(f'Перезапускаю {", ".join(args.services) or "все сервисы"}')
    compose('restart', *args.services)


def cmd_status(args):
    """Показывает, какие сервисы запущены."""
    compose('ps')


def cmd_logs(args):
    """Показывает логи в реальном времени."""
    compose('logs', '-f', f'--tail={args.tail}', *args.services, check=False)


def latest_release():
    """Скачивает теги и возвращает последний релиз (vX.Y.Z) или None."""
    git('fetch', '--tags', '--force', '--quiet')
    tags = git('tag', '--list', 'v*', '--sort=-v:refname', capture=True).stdout.split()
    return tags[0] if tags else None


def head():
    """Возвращает хеш текущего коммита."""
    return git('rev-parse', 'HEAD', capture=True).stdout.strip()


def cmd_update(args):
    """Обновляет сайт до последнего релиза (или до master с --dev) и перезапускает его."""
    if git('diff', '--quiet', 'HEAD', '--', check=False).returncode != 0:
        warn('В папке сайта есть изменённые файлы — если они мешают обновлению, git сообщит об этом.')

    before = head()
    info('Проверяю обновления')
    release = None if args.dev else latest_release()

    if args.dev or release is None:
        if release is None and not args.dev:
            warn('Релизов пока нет — обновляю до текущей версии master.')
        if git('symbolic-ref', '--quiet', 'HEAD', check=False, capture=True).returncode != 0:
            git('checkout', '--quiet', 'master')
        if git('pull', '--ff-only', check=False).returncode != 0:
            raise GuildError(f'Не удалось скачать обновления. Если вы меняли файлы сайта, отложите изменения: git -C {ROOT} stash')
    else:
        target = git('rev-parse', f'{release}^{{commit}}', capture=True).stdout.strip()
        newer = git('merge-base', '--is-ancestor', target, before, check=False).returncode == 0
        if target != before and newer:
            info(f'У вас версия новее последнего релиза {release}. Обновить её из master: guild update --dev')
        elif target != before:
            if git('checkout', '--quiet', '--detach', release, check=False).returncode != 0:
                raise GuildError(f'Не удалось перейти на {release}. Если вы меняли файлы сайта, отложите изменения: git -C {ROOT} stash')

    after = head()
    if before == after and not args.force:
        info(f'Установлена последняя версия ({version_string()}). Пересобрать всё равно: guild update --force')
        return

    if before != after:
        print(f'\n{BOLD}Что нового:{RESET}')
        git('log', '--format=  - %s', f'{before}..{after}')
        print()

    info('Собираю и перезапускаю сайт')
    compose('up', '-d', '--build', '--remove-orphans')
    info('Удаляю старые образы')
    run('docker', 'image', 'prune', '-f', check=False, capture=True)
    info(f'Готово, версия {version_string()}')


def cmd_backup(args):
    """Делает резервную копию сейчас."""
    info('Делаю резервную копию')
    manage('backup_now')


def cmd_restore(args):
    """Показывает список копий или восстанавливает выбранную."""
    options = []
    if args.from_yandex:
        options.append('--from-yandex')
    if args.no_media:
        options.append('--no-media')
    manage('restore_backup', *([args.file] if args.file else []), *options)
    # Без файла команда только показывает список копий.
    if args.file:
        info('Перезапускаю сайт')
        compose('restart', 'web', 'scheduler')


def cmd_admin(args):
    """Добавляет администратора сайта."""
    manage('createsuperuser')


def cmd_manage(args):
    """Запускает любую команду Django."""
    if not args.command:
        raise GuildError('Укажите команду Django, например: guild manage check_auctions')
    manage(*args.command)


def cmd_shell(args):
    """Открывает консоль Django."""
    manage('shell')


def cmd_ts_key(args):
    """Показывает ключ администратора TeamSpeak из логов бота."""
    key = find_ts_key()
    if not key:
        warn('Ключа нет в логах бота: администратор TeamSpeak уже назначен или бот ещё не запускался. Логи: guild logs tsbot')
        return
    print('Ключ администратора TeamSpeak — введите его в клиенте: Права → Использовать ключ привилегий')
    print(f'    {key}')


def cmd_info(args):
    """Показывает адреса сайта и TeamSpeak и ключ TeamSpeak, если он ещё не использован."""
    domains = site_domains()
    site = f'https://{domains[0]}' if domains else '(DOMAIN не задан в .env)'
    print(f'{BOLD}Сайт гильдии{RESET}, версия {version_string()}, папка {ROOT}\n')
    print(f'  Сайт:               {site}')
    print(f'  Админ-панель:       {site}/admin/')
    print(f'  Адрес TeamSpeak:    {ts_address() or "(сайт не запущен)"}')
    key = find_ts_key()
    if key:
        print(f'  Ключ TeamSpeak:     {key}  (Права → Использовать ключ привилегий)')
    print(f'  Пароль шифрования копий — BACKUP_ENCRYPTION_PASSWORD в {ENV_FILE}')


def cmd_version(args):
    """Показывает установленную версию."""
    print(f'Версия: {version_string()}')


def cmd_install(args):
    """Создаёт ссылку /usr/local/bin/guild на этот скрипт."""
    if not os.access(LINK.parent, os.W_OK):
        raise GuildError(f'Нет прав на запись в {LINK.parent}. Запустите: sudo python3 {SCRIPT} install')
    SCRIPT.chmod(SCRIPT.stat().st_mode | 0o111)
    if LINK.is_symlink() or LINK.exists():
        LINK.unlink()
    LINK.symlink_to(SCRIPT)
    info('Команда guild установлена. Список команд: guild help')


def cmd_uninstall(args):
    """Удаляет ссылку /usr/local/bin/guild, если она указывает на этот скрипт."""
    if not LINK.is_symlink() or LINK.resolve() != SCRIPT:
        raise GuildError(f'Команда guild из этой папки не установлена в {LINK}')
    if not os.access(LINK.parent, os.W_OK):
        raise GuildError(f'Нет прав на запись в {LINK.parent}. Запустите: sudo guild uninstall')
    LINK.unlink()
    info(f'Команда guild удалена. Сайт продолжает работать, управлять им можно через python3 {SCRIPT}')


# Установка: guild setup. Сначала все проверки и вопросы, потом долгие шаги.

def ask(question, default=None, preset=None, option='', validate=None):
    """Спрашивает значение у пользователя.

    Аргументы:
        default: значение по Enter.
        preset: значение из параметра командной строки — тогда вопрос не задается.
        option: имя параметра для подсказки, если терминала нет.
        validate: функция, возвращающая текст ошибки или None.
    """
    if preset is not None:
        error = validate(preset) if validate else None
        if error:
            raise GuildError(f'{option}: {error}')
        return preset
    if not sys.stdin.isatty():
        if default is not None:
            return default
        raise GuildError(f'Нет терминала для вопроса «{question}» — укажите {option}')
    while True:
        suffix = f' [{default}]' if default else ''
        value = input(f'{question}{suffix}: ').strip() or (default or '')
        error = validate(value) if validate else None
        if not error:
            return value
        print(f'  {FAIL} {error}')


def confirm(question, assume_yes):
    """Задает вопрос да/нет. При --yes отвечает «да», без терминала — «нет»."""
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        return False
    return input(f'{question} [y/N]: ').strip().lower() in ('y', 'yes', 'д', 'да')


DOMAIN_RE = re.compile(r'^(?=.{1,253}$)((?!-)[a-z0-9-]{1,63}(?<!-)\.)+[a-z0-9-]{2,63}$')


def to_ascii(domain):
    """Переводит домен в нижний регистр и punycode: гильдия.рф -> xn--....xn--p1ai."""
    domain = domain.strip().lower().rstrip('.')
    try:
        return domain.encode('idna').decode('ascii')
    except UnicodeError:
        return domain


def split_domains(value):
    """Разбивает список доменов через запятую и переводит их в punycode."""
    return [to_ascii(d) for d in value.split(',') if d.strip()]


def validate_domain(value):
    """Проверяет имя домена."""
    if DOMAIN_RE.match(to_ascii(value)):
        return None
    return f'«{value}» не похоже на домен, пример: myguild.ru'


def validate_domains(value):
    """Проверяет список доменов через запятую."""
    domains = [d for d in value.split(',') if d.strip()]
    if not domains:
        return 'Укажите домен, например: myguild.ru'
    for domain in domains:
        error = validate_domain(domain)
        if error:
            return error
    return None


def validate_login(value):
    """Проверяет логин администратора."""
    if value.lower() in RESERVED_LOGINS:
        return f'Логин «{value}» слишком очевиден — его подбирают первым. Выберите другой'
    if not re.match(r'^[\w.@+-]{3,150}$', value):
        return 'Логин — от 3 символов: буквы, цифры и . @ + - _'
    return None


def public_ip(version):
    """Определяет внешний IP сервера через публичный сервис или возвращает None."""
    urls = {
        4: ('https://api.ipify.org', 'https://ipv4.icanhazip.com'),
        6: ('https://api6.ipify.org', 'https://ipv6.icanhazip.com'),
    }[version]
    for url in urls:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                address = ipaddress.ip_address(response.read().decode().strip())
        except (OSError, ValueError):
            continue
        if address.version == version:
            return str(address)
    return None


def dig(record_type, name):
    """Возвращает строки ответа публичного DNS или None, если dig недоступен."""
    if not shutil.which('dig'):
        return None
    for resolver in RESOLVERS:
        result = run('dig', '+short', '+time=3', '+tries=1', record_type, name, f'@{resolver}', check=False, capture=True)
        if result.returncode == 0:
            return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return None


def resolve(name):
    """Возвращает IPv4- и IPv6-адреса домена."""
    found = {4: set(), 6: set()}
    for version, record_type in ((4, 'A'), (6, 'AAAA')):
        lines = dig(record_type, name)
        if lines is None:
            break
        for line in lines:
            try:
                address = ipaddress.ip_address(line)
            except ValueError:
                continue  # CNAME в ответе
            if address.version == version:
                found[version].add(str(address))
    else:
        return found

    # Без dig — через системный резолвер.
    try:
        for family, *_, sockaddr in socket.getaddrinfo(name, None):
            found[4 if family == socket.AF_INET else 6].add(sockaddr[0])
    except socket.gaierror:
        pass
    return found


def domain_problems(name, ip4, ip6, voice):
    """Возвращает список проблем DNS для домена (пустой, если всё в порядке)."""
    found = resolve(name)
    problems = []
    if not found[4]:
        problems.append(f'{name}: нет A-записи')
    elif ip4 and ip4 not in found[4]:
        hint = ('для этой записи в Cloudflare включите режим «DNS only» (серое облако) — через прокси голос не работает'
                if voice else 'если домен за прокси Cloudflare, это нормально — выберите «продолжить»')
        problems.append(f'{name} указывает на {", ".join(sorted(found[4]))}, а IP этого сервера {ip4}: {hint}')
    if found[6] and (not ip6 or ip6 not in found[6]):
        problems.append(f'{name}: AAAA-запись {", ".join(sorted(found[6]))} ведёт не на этот сервер — удалите её, '
                        f'иначе часть посетителей не попадёт на сайт, а сертификат не выдадут')
    return problems


def srv_ok(domain, ts_domain):
    """Проверяет SRV-запись _ts3._udp. Возвращает None, если проверить нечем."""
    lines = dig('SRV', f'_ts3._udp.{domain}')
    if lines is None:
        return None
    for line in lines:
        parts = line.split()
        if len(parts) == 4 and parts[2] == str(TS_PORT) and parts[3].rstrip('.').lower() == ts_domain.lower():
            return True
    return False


def print_dns_records(domains, ts_domain, ip4):
    """Печатает записи DNS, которые нужно создать у регистратора."""
    ip = ip4 or '<IP сервера>'
    rows = [('A', name, ip, '') for name in domains]
    if ts_domain not in domains:
        rows.append(('A', ts_domain, ip, 'для TeamSpeak, без прокси Cloudflare'))
        rows.append(('SRV', f'_ts3._udp.{domains[0]}', f'0 5 {TS_PORT} {ts_domain}',
                     f'необязательно: игроки смогут вводить {domains[0]}'))
    print(f'\n{BOLD}Записи DNS у регистратора домена{RESET} (подробнее — docs/GUIDE.md, «DNS для TeamSpeak»):')
    width = max(len(row[1]) for row in rows)
    for kind, name, value, note in rows:
        print(f'  {kind:<4} {name:<{width}}  {value}' + (f'   — {note}' if note else ''))
    print()


def check_dns(domains, ts_domain, assume_yes):
    """Проверяет DNS, пока записи не станут верными или пользователь не решит продолжить.

    Возвращает пару: настроена ли SRV-запись TeamSpeak и верны ли записи сайта и TeamSpeak.
    """
    info('Определяю IP сервера')
    ip4, ip6 = public_ip(4), public_ip(6)
    if ip4:
        print(f'  IP сервера: {ip4}' + (f', IPv6: {ip6}' if ip6 else ''))
    else:
        warn('Не удалось определить внешний IP сервера — сверьте записи DNS сами.')
    print_dns_records(domains, ts_domain, ip4)

    while True:
        info('Проверяю DNS')
        problems = []
        for name in dict.fromkeys(domains + [ts_domain]):
            found = domain_problems(name, ip4, ip6, voice=name == ts_domain)
            print(f'  {FAIL if found else OK} {name}')
            problems += found
        for problem in problems:
            print(f'    {YELLOW}{problem}{RESET}')

        srv = srv_ok(domains[0], ts_domain) if ts_domain not in domains else None
        if srv is not None:
            print(f'  {OK if srv else "-"} SRV _ts3._udp.{domains[0]}' + ('' if srv else ' не настроена (необязательно)'))

        if not problems:
            return bool(srv), True
        if assume_yes:
            warn('Продолжаю с ошибками DNS (--yes). Сайт откроется, когда записи обновятся.')
            return bool(srv), False
        if not sys.stdin.isatty():
            raise GuildError('Записи DNS не готовы. Исправьте их или добавьте --yes, чтобы продолжить всё равно.')
        print('\nDNS обновляется от нескольких минут до нескольких часов.')
        answer = input('Enter — проверить снова, c — продолжить всё равно, q — выйти: ').strip().lower()
        if answer == 'q':
            raise GuildError('Установка прервана. Когда записи DNS обновятся, запустите её снова: sudo guild setup')
        if answer == 'c':
            return bool(srv), False


def busy_ports():
    """Возвращает строки о занятых портах, которые нужны сайту и TeamSpeak."""
    result = run('ss', '-Htulnp', check=False, capture=True)
    busy = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        port = parts[4].rpartition(':')[2]
        if port.isdigit() and (parts[0], int(port)) in PORTS:
            program = re.search(r'\("([^"]+)"', line)
            busy.append(f'{parts[0]} {port} — {program.group(1) if program else "неизвестная программа"}')
    return sorted(set(busy))


def daemon_ready():
    """Проверяет, что служба Docker запущена."""
    return run('docker', 'info', check=False, capture=True).returncode == 0


def ensure_docker():
    """Устанавливает Docker, если его нет, и проверяет, что служба запущена."""
    if not docker_ready():
        info(f'Устанавливаю Docker — это займёт пару минут (лог: {LOG})')
        with open(LOG, 'a', encoding='utf-8') as log:
            result = subprocess.run(['sh', '-c', 'curl -fsSL https://get.docker.com | sh'],
                                    stdout=log, stderr=subprocess.STDOUT)
        if result.returncode != 0 or not docker_ready():
            raise GuildError(f'Не удалось установить Docker, подробности в {LOG}')
    if not daemon_ready():
        run('systemctl', 'enable', '--now', 'docker', check=False, capture=True)
    if not daemon_ready():
        raise GuildError('Docker установлен, но не запущен. Посмотрите причину: systemctl status docker')


def ask_ts_license(accepted):
    """Спрашивает согласие с лицензией TeamSpeak."""
    if accepted:
        return
    if not sys.stdin.isatty():
        raise GuildError('Для установки без вопросов подтвердите лицензию TeamSpeak: --accept-ts-license')
    print(f'\n{BOLD}TeamSpeak 3{RESET} — бесплатный для некоммерческого использования, но со своей лицензией.')
    while True:
        answer = input('Принимаете лицензию TeamSpeak? y — да, v — прочитать (сначала установится Docker), n — нет: ').strip().lower()
        if answer in ('y', 'yes', 'д', 'да'):
            return
        if answer in ('n', 'no', 'н', 'нет'):
            raise GuildError('Без согласия с лицензией TeamSpeak установка невозможна.')
        if answer == 'v':
            ensure_docker()
            subprocess.run(['docker', 'run', '--rm', '-e', 'TS3SERVER_LICENSE=view', 'teamspeak:3.13'])


def write_env(values):
    """Создает .env из .env.example с подставленными значениями и правами 600."""
    lines = []
    for line in (ROOT / '.env.example').read_text(encoding='utf-8').splitlines():
        key = line.partition('=')[0].strip()
        if not line.lstrip().startswith('#') and key in values:
            line = f'{key}={values[key]}'
        lines.append(line)
    fd = os.open(ENV_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as file:
        file.write('\n'.join(lines) + '\n')


def wait(description, check, timeout):
    """Ждет, пока check() вернет истину, не дольше timeout секунд. Возвращает результат check()."""
    print(f'  {description} (до {timeout // 60} мин)...', end='', flush=True)
    deadline = time.monotonic() + timeout
    while True:
        result = check()
        if result or time.monotonic() > deadline:
            print(f' {OK}' if result else f' {FAIL}')
            return result
        print('.', end='', flush=True)
        time.sleep(5)


# Скрипт выполняется внутри контейнера web. Пароль передается через stdin, а не в аргументах,
# чтобы не попасть в список процессов. Если установка прервалась после создания администратора,
# его пароль никто не видел — при продолжении он задается заново.
CREATE_ADMIN = '''
import json, os, sys
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from django.contrib.auth.models import User
data = json.load(sys.stdin)
user = User.objects.filter(username=data['username']).first()
if user is None:
    User.objects.create_superuser(data['username'], '', data['password'])
elif user.is_superuser:
    user.set_password(data['password'])
    user.save(update_fields=['password'])
else:
    sys.exit('Пользователь с таким логином уже есть и не является администратором')
'''


def site_responds(domain):
    """Проверяет, что сайт открывается по HTTPS с действительным сертификатом."""
    try:
        with urllib.request.urlopen(f'https://{domain}/', timeout=10):
            return True
    except urllib.error.HTTPError:
        return True  # Сайт ответил, сертификат в порядке
    except OSError:
        return False


def setup_existing(args):
    """Поведение setup на уже установленном сайте: ничего не перегенерирует."""
    print(f'{BOLD}Сайт уже установлен{RESET} в {ROOT}, версия {version_string()}.')
    print('Настройки (.env) не меняются: пароль базы применяется только при первом запуске,')
    print('новый пароль отрезал бы сайт от базы.\n')
    if not sys.stdin.isatty():
        cmd_info(args)
        return
    answer = input('i — данные для входа, u — обновить, Enter — выйти: ').strip().lower()
    if answer == 'i':
        cmd_info(args)
    elif answer == 'u':
        cmd_update(argparse.Namespace(dev=False, force=False))


def cmd_setup(args):
    """Первая установка: вопросы, проверка DNS, Docker, .env, запуск и итоговые данные для входа."""
    require_root('setup')
    if ENV_FILE.exists():
        ensure_docker()
        if SETUP_STATE.exists():
            info('Продолжаю незавершённую установку')
            finish_setup(json.loads(SETUP_STATE.read_text(encoding='utf-8')))
        else:
            setup_existing(args)
        return

    print(f'{BOLD}Установка сайта гильдии{RESET}, версия {version_string()}\n')

    if shutil.which('ss'):
        busy = busy_ports()
        if busy:
            warn('Заняты порты, которые нужны сайту и TeamSpeak:')
            for line in busy:
                warn(f'  {line}')
            warn('Остановите или удалите эти программы (например, nginx или apache2), иначе сайт не запустится.')
            if not confirm('Продолжить всё равно?', args.yes):
                raise GuildError('Установка прервана.')

    domains_text = ask('Домен сайта (несколько — через запятую)', preset=args.domain, option='--domain',
                       validate=validate_domains)
    domains = split_domains(domains_text)
    ts_domain = to_ascii(ask('Домен TeamSpeak', default=f'ts.{domains[0]}', preset=args.ts_domain,
                             option='--ts-domain', validate=validate_domain))
    srv, dns_ok = check_dns(domains, ts_domain, args.yes)

    login = ask('Логин администратора сайта', default='guildmaster', preset=args.admin, option='--admin',
                validate=validate_login)
    ask_ts_license(args.accept_ts_license)

    ensure_docker()

    info('Создаю настройки (.env)')
    state = {'domain': domains[0], 'ts_domain': ts_domain, 'srv': srv, 'dns_ok': dns_ok, 'login': login}
    SETUP_STATE.write_text(json.dumps(state), encoding='utf-8')
    write_env({
        'DOMAIN': ', '.join(domains),
        'DJANGO_SECRET_KEY': secrets.token_urlsafe(50),
        'POSTGRES_PASSWORD': secrets.token_hex(24),
        'BACKUP_ENCRYPTION_PASSWORD': secrets.token_urlsafe(24),
        'TS3SERVER_LICENSE': 'accept',
        'TS3_SERVERADMIN_PASSWORD': secrets.token_hex(16),
        'TSBOT_API_TOKEN': secrets.token_hex(32),
    })
    cmd_install(args)
    finish_setup(state)


def finish_setup(state):
    """Запускает сайт, создает администратора и печатает данные для входа.

    Если шаг не удался, повторный guild setup продолжит отсюда: .env уже создан,
    а данные установки лежат в SETUP_STATE.
    """
    domain, ts_domain, srv, login = state['domain'], state['ts_domain'], state['srv'], state['login']
    resume = 'Исправьте причину и продолжите установку: sudo guild setup'

    info('Собираю и запускаю сайт — первый запуск занимает несколько минут')
    if compose('up', '-d', '--build', check=False).returncode != 0:
        raise GuildError(f'Не удалось запустить сайт. {resume}')

    info('Жду готовности')
    if not wait('База данных и миграции', lambda: manage('migrate', '--check', capture=True, check=False).returncode == 0, 300):
        raise GuildError(f'Сайт не запустился за 5 минут. Посмотрите логи: guild logs web. {resume}')
    password = secrets.token_urlsafe(18)
    result = compose('exec', '-T', 'web', 'python', '-c', CREATE_ADMIN, check=False, capture=True,
                     input=json.dumps({'username': login, 'password': password}))
    if result.returncode != 0:
        raise GuildError(f'Не удалось создать администратора: {result.stderr.strip()}. {resume}')
    manage('ts_address', ts_domain, capture=True)
    SETUP_STATE.unlink()

    ts_key = wait('Сервер TeamSpeak и бот', find_ts_key, 180)
    # Пока домен не указывает на сервер, сертификат не выдадут — ждать незачем.
    https = state.get('dns_ok', True) and wait('HTTPS-сертификат', lambda: site_responds(domain), 120)
    backup_password = read_env().get('BACKUP_ENCRYPTION_PASSWORD', '')

    print(f'\n{GREEN}{BOLD}Сайт установлен!{RESET}\n')
    print(f'  Сайт:                {BOLD}https://{domain}{RESET}')
    print(f'  Админ-панель:        https://{domain}/admin/')
    print(f'  Логин:               {BOLD}{login}{RESET}')
    print(f'  Пароль:              {BOLD}{password}{RESET}')
    print(f'  Адрес TeamSpeak:     {BOLD}{domain if srv else ts_domain}{RESET}')
    if ts_key:
        print(f'  Ключ TeamSpeak:      {BOLD}{ts_key}{RESET}')
        print('                       в клиенте: Права → Использовать ключ привилегий — вы станете администратором')
    else:
        print('  Ключ TeamSpeak:      бот ещё запускается — посмотрите позже: guild ts-key')
    print(f'\n  {YELLOW}{BOLD}Пароль шифрования резервных копий: {backup_password}{RESET}')
    print(f'  {YELLOW}Сохраните его в менеджере паролей вне сервера: без него копии не восстановить.{RESET}')
    print(f'  {YELLOW}Пароль администратора больше нигде не показывается — сохраните его и смените после входа.{RESET}')
    if not https:
        print('\n  Сайт пока не открывается по HTTPS: сертификат выдадут сами, когда записи DNS начнут указывать')
        print('  на этот сервер. Если через пару часов не откроется — guild logs caddy')
    print('\n  Откройте в файрволе хостинга порты 80, 443 (TCP) и 9987 (UDP), 30033 (TCP) для TeamSpeak.')
    print('  Управление сайтом: guild (меню) или guild help. Данные для входа (без паролей): guild info')


# Пункты меню: команда и подпись.
MENU = [
    ('status', 'Что запущено'),
    ('info', 'Адреса и ключ TeamSpeak'),
    ('start', 'Запустить'),
    ('stop', 'Остановить'),
    ('restart', 'Перезапустить'),
    ('update', 'Обновить'),
    ('logs', 'Логи'),
    ('backup', 'Сделать резервную копию'),
    ('restore', 'Список резервных копий'),
    ('version', 'Версия'),
]


def cmd_menu(args):
    """Показывает меню с номерами команд и выполняет выбранную."""
    print(f'{BOLD}Сайт гильдии{RESET} — версия {version_string()}\n')
    for number, (_, title) in enumerate(MENU, start=1):
        print(f'  {number:2}. {title}')
    print('   0. Выход\n')

    choice = input('Выберите пункт: ').strip()
    if choice in ('', '0'):
        return
    if not choice.isdigit() or not 1 <= int(choice) <= len(MENU):
        raise GuildError(f'Нет такого пункта: {choice}')
    dispatch([MENU[int(choice) - 1][0]])


def build_parser():
    """Описывает команды и их аргументы."""
    parser = argparse.ArgumentParser(
        prog='guild',
        description=f'Управление сайтом гильдии (папка сайта: {ROOT}). Без команды — меню.',
        epilog='Данные (база, картинки, копии) хранятся в томах Docker и не удаляются при stop, restart и update.',
    )
    commands = parser.add_subparsers(dest='name', metavar='команда', title='команды')

    def add(name, handler, help_text, aliases=()):
        sub = commands.add_parser(name, help=help_text, description=help_text, aliases=list(aliases))
        sub.set_defaults(handler=handler)
        return sub

    add('start', cmd_start, 'запустить сайт (или применить изменения .env)')
    add('stop', cmd_stop, 'остановить сайт')
    add('restart', cmd_restart, 'перезапустить всё или выбранные сервисы').add_argument(
        'services', nargs='*', metavar='сервис', help='web, scheduler, caddy, db, teamspeak, tsbot')
    add('status', cmd_status, 'что запущено', aliases=['ps'])
    add('info', cmd_info, 'адреса сайта и TeamSpeak, ключ TeamSpeak')
    logs = add('logs', cmd_logs, 'логи в реальном времени (Ctrl+C — выход)')
    logs.add_argument('services', nargs='*', metavar='сервис', help='по умолчанию — все сервисы')
    logs.add_argument('-n', '--tail', type=int, default=200, help='сколько последних строк показать (200)')
    update = add('update', cmd_update, 'обновить до последнего релиза и перезапустить')
    update.add_argument('--force', action='store_true', help='пересобрать, даже если обновлений нет')
    update.add_argument('--dev', action='store_true', help='обновить до текущей версии master, а не до релиза')

    add('backup', cmd_backup, 'сделать резервную копию сейчас')
    restore = add('restore', cmd_restore, 'без файла — список копий, с файлом — восстановить')
    restore.add_argument('file', nargs='?', metavar='файл', help='например backup-20261019-040000.tar.gz.gpg')
    restore.add_argument('--from-yandex', action='store_true', help='скачать копию с Яндекс Диска')
    restore.add_argument('--no-media', action='store_true', help='восстановить только базу')
    add('admin', cmd_admin, 'добавить администратора сайта')

    add('ts-key', cmd_ts_key, 'ключ администратора TeamSpeak')

    add('manage', cmd_manage, 'любая команда Django: guild manage check_auctions').add_argument(
        'command', nargs=argparse.REMAINDER, metavar='команда')
    add('shell', cmd_shell, 'консоль Django')
    add('version', cmd_version, 'установленная версия')

    setup = add('setup', cmd_setup, 'первая установка: DNS, Docker, настройки и запуск (нужен sudo)')
    setup.add_argument('--domain', help='домен сайта, несколько — через запятую')
    setup.add_argument('--ts-domain', help='домен TeamSpeak (по умолчанию ts.<домен сайта>)')
    setup.add_argument('--admin', help='логин администратора сайта')
    setup.add_argument('--accept-ts-license', action='store_true', help='принять лицензию TeamSpeak')
    setup.add_argument('--yes', action='store_true', help='не останавливаться на ошибках DNS и занятых портах')
    add('install', cmd_install, 'установить команду guild в систему (нужен sudo)')
    add('uninstall', cmd_uninstall, 'удалить команду guild из системы')
    add('menu', cmd_menu, 'меню с выбором команды')
    return parser


# Команды, которым не нужны готовые Docker и .env.
NO_SETUP = {cmd_setup, cmd_install, cmd_uninstall, cmd_version}


def dispatch(argv):
    """Разбирает аргументы и выполняет команду."""
    args = build_parser().parse_args(argv)
    handler = getattr(args, 'handler', cmd_menu)
    if handler not in NO_SETUP:
        require_setup()
    handler(args)


def main():
    # Построчный вывод: иначе при выводе в файл или pipe сообщения перемешиваются со stderr.
    sys.stdout.reconfigure(line_buffering=True)
    try:
        dispatch(sys.argv[1:])
    except GuildError as error:
        print(f'{RED}Ошибка:{RESET} {error}', file=sys.stderr)
        sys.exit(1)
    except (KeyboardInterrupt, EOFError):
        print()
        sys.exit(130)


if __name__ == '__main__':
    main()
