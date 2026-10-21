#!/usr/bin/env python3
"""Управление сайтом гильдии на сервере: запуск, обновление, логи, резервные копии.

Работает из любой папки — папку сайта находит по своему расположению.
Только стандартная библиотека и Python 3.8+, чтобы запускаться системным Python сервера.

Установить команду guild в систему: sudo python3 cli/guild.py install
Список команд: guild help
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Настоящий путь к скрипту, даже если guild запущен через ссылку из /usr/local/bin.
SCRIPT = Path(__file__).resolve()
ROOT = SCRIPT.parent.parent
LINK = Path('/usr/local/bin/guild')

if sys.stdout.isatty():
    BOLD, GREEN, YELLOW, RED, RESET = '\033[1m', '\033[32m', '\033[33m', '\033[31m', '\033[0m'
else:
    BOLD = GREEN = YELLOW = RED = RESET = ''


class GuildError(Exception):
    """Ошибка, после которой команда завершается с понятным сообщением."""


def info(message):
    """Печатает шаг выполнения команды."""
    print(f'{GREEN}==>{RESET} {BOLD}{message}{RESET}', flush=True)


def warn(message):
    """Печатает предупреждение в stderr."""
    print(f'{YELLOW}{message}{RESET}', file=sys.stderr, flush=True)


def run(*args, check=True, capture=False):
    """Запускает программу в папке сайта и возвращает CompletedProcess.

    Аргументы:
        check: при ненулевом коде возврата завершить guild с тем же кодом.
        capture: вернуть вывод программы, а не печатать его.
    """
    result = subprocess.run(args, cwd=ROOT, capture_output=capture, encoding='utf-8', errors='replace')
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


def manage(*args):
    """Запускает manage.py в контейнере web."""
    # Без терминала (например, из cron) docker compose exec нужно запускать с -T.
    tty = [] if sys.stdin.isatty() else ['-T']
    compose('exec', *tty, 'web', 'python', 'manage.py', *args)


def version_string():
    """Возвращает версию сайта: короткий хеш и дату последнего коммита."""
    result = git('log', '-1', '--format=%h от %cd', '--date=format:%d.%m.%Y', check=False, capture=True)
    return result.stdout.strip() or 'неизвестна'


def require_setup():
    """Проверяет, что установлен Docker и создан .env."""
    if not shutil.which('docker'):
        raise GuildError('Docker не установлен. Установка: curl -fsSL https://get.docker.com | sh')
    if run('docker', 'compose', 'version', check=False, capture=True).returncode != 0:
        raise GuildError('Не найден docker compose. Обновите Docker.')
    if not (ROOT / '.env').exists():
        raise GuildError(f'Нет файла {ROOT / ".env"}. Создайте его: cp .env.example .env — и заполните (см. README).')


# Команды. Каждая получает разобранные аргументы argparse.

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


def cmd_update(args):
    """Скачивает новую версию, пересобирает и перезапускает сайт."""
    if git('diff', '--quiet', 'HEAD', '--', check=False).returncode != 0:
        warn('В папке сайта есть изменённые файлы — если они мешают обновлению, git сообщит об этом.')

    before = git('rev-parse', 'HEAD', capture=True).stdout.strip()
    info('Скачиваю обновления')
    if git('pull', '--ff-only', check=False).returncode != 0:
        raise GuildError(f'Не удалось скачать обновления. Если вы меняли файлы сайта, отложите изменения: git -C {ROOT} stash')
    after = git('rev-parse', 'HEAD', capture=True).stdout.strip()

    if before == after and not args.force:
        info('Установлена последняя версия. Пересобрать всё равно: guild update --force')
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
    lines = compose('logs', '--no-log-prefix', 'tsbot', check=False, capture=True).stdout.splitlines()
    # Бот печатает ключ строкой ниже заголовка (tsbot/tsbot/setup.py).
    keys = [lines[i + 1].strip() for i, line in enumerate(lines[:-1]) if 'Ключ администратора TeamSpeak' in line]
    if not keys:
        warn('Ключа нет в логах бота: администратор TeamSpeak уже назначен или бот ещё не запускался. Логи: guild logs tsbot')
        return
    print('Ключ администратора TeamSpeak — введите его в клиенте: Права → Использовать ключ привилегий')
    print(f'    {keys[-1]}')


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


# Пункты меню: команда и подпись.
MENU = [
    ('status', 'Что запущено'),
    ('start', 'Запустить'),
    ('stop', 'Остановить'),
    ('restart', 'Перезапустить'),
    ('update', 'Обновить'),
    ('logs', 'Логи'),
    ('backup', 'Сделать резервную копию'),
    ('restore', 'Список резервных копий'),
    ('ts-key', 'Ключ администратора TeamSpeak'),
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
    logs = add('logs', cmd_logs, 'логи в реальном времени (Ctrl+C — выход)')
    logs.add_argument('services', nargs='*', metavar='сервис', help='по умолчанию — все сервисы')
    logs.add_argument('-n', '--tail', type=int, default=200, help='сколько последних строк показать (200)')
    add('update', cmd_update, 'обновить до новой версии и перезапустить').add_argument(
        '--force', action='store_true', help='пересобрать, даже если обновлений нет')

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
    add('install', cmd_install, 'установить команду guild в систему (нужен sudo)')
    add('uninstall', cmd_uninstall, 'удалить команду guild из системы')
    add('menu', cmd_menu, 'меню с выбором команды')
    return parser


# Команды, которым не нужны Docker и .env.
NO_SETUP = {cmd_install, cmd_uninstall, cmd_version}


def dispatch(argv):
    """Разбирает аргументы и выполняет команду."""
    args = build_parser().parse_args(argv)
    handler = getattr(args, 'handler', cmd_menu)
    if handler not in NO_SETUP:
        require_setup()
    handler(args)


def main():
    try:
        dispatch(sys.argv[1:])
    except GuildError as error:
        print(f'{RED}Ошибка:{RESET} {error}', file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print()
        sys.exit(130)


if __name__ == '__main__':
    main()
