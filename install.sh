#!/usr/bin/env bash
# Установка сайта гильдии одной командой на сервер с Ubuntu или Debian:
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/THEChrismoth/Perfect_World_guild_forum/master/install.sh)
#
# Скрипт проверяет сервер, ставит нужные пакеты, скачивает последний релиз в /opt/guild-forum
# и передает работу утилите guild (cli/guild.py setup): вопросы, проверка DNS, Docker, .env и запуск.
# Параметры передаются в guild setup, без вопросов можно установить так:
#   ... install.sh) --domain myguild.ru --ts-domain ts.myguild.ru --admin leader --accept-ts-license --yes
set -euo pipefail

REPO=https://github.com/THEChrismoth/Perfect_World_guild_forum.git
DIR="${GUILD_DIR:-/opt/guild-forum}"
LOG=/var/log/guild-install.log

if [ -t 1 ]; then
    BOLD=$'\e[1m' GREEN=$'\e[32m' YELLOW=$'\e[33m' RED=$'\e[31m' RESET=$'\e[0m'
else
    BOLD='' GREEN='' YELLOW='' RED='' RESET=''
fi

info() { echo "${GREEN}==>${RESET} ${BOLD}$*${RESET}"; }
warn() { echo "${YELLOW}$*${RESET}" >&2; }
die() { echo "${RED}Ошибка:${RESET} $*" >&2; exit 1; }

check_system() {
    [ "$(id -u)" -eq 0 ] || die "Запустите установку от root: sudo -i, затем команду установки ещё раз."

    # Образ TeamSpeak 3 есть только для x86-64.
    [ "$(uname -m)" = x86_64 ] || die "Нужен сервер с процессором x86-64, а у этого $(uname -m): TeamSpeak 3 на нём не запустится."

    [ -r /etc/os-release ] || die "Не удалось определить систему. Поддерживаются Ubuntu 22.04, 24.04 и Debian 12, 13."
    . /etc/os-release
    case "${ID:-}" in
        ubuntu|debian) ;;
        *) die "Система ${PRETTY_NAME:-неизвестна} не поддерживается. Поддерживаются Ubuntu 22.04, 24.04 и Debian 12, 13." ;;
    esac
    case "$ID ${VERSION_ID:-}" in
        'ubuntu 22.04'|'ubuntu 24.04'|'debian 12'|'debian 13') ;;
        *) warn "Установка проверялась на Ubuntu 22.04, 24.04 и Debian 12, 13, а у вас $PRETTY_NAME — возможны ошибки." ;;
    esac

    local memory
    memory="$(awk '/^MemTotal:/ {print int($2 / 1024)}' /proc/meminfo)"
    [ "$memory" -ge 900 ] || warn "Памяти ${memory} МБ, а нужно хотя бы 1 ГБ — сайт может работать нестабильно."
}

install_packages() {
    info "Устанавливаю пакеты (лог: $LOG)"
    export DEBIAN_FRONTEND=noninteractive
    # На свежем сервере apt часто занят автообновлениями — ждём, а не падаем.
    {
        apt-get -o DPkg::Lock::Timeout=300 update
        apt-get -o DPkg::Lock::Timeout=300 install -y ca-certificates curl git python3 openssl bind9-dnsutils iproute2
    } >>"$LOG" 2>&1 || die "Не удалось установить пакеты, подробности в $LOG"
}

download() {
    if [ -d "$DIR/.git" ]; then
        info "Сайт уже скачан в $DIR"
        return
    fi

    local tag
    tag="$(git ls-remote --tags --refs --sort=-v:refname "$REPO" 'v*' | head -n1 | sed 's#.*refs/tags/##')"
    if [ -n "$tag" ]; then
        info "Скачиваю версию $tag в $DIR"
        git clone --quiet --branch "$tag" "$REPO" "$DIR" 2>>"$LOG" || die "Не удалось скачать сайт, подробности в $LOG"
    else
        warn "Релизов пока нет — скачиваю текущую версию из master."
        git clone --quiet "$REPO" "$DIR" 2>>"$LOG" || die "Не удалось скачать сайт, подробности в $LOG"
    fi
}

main() {
    check_system
    install_packages
    download
    exec python3 "$DIR/cli/guild.py" setup "$@"
}

# Весь скрипт читается до запуска: если загрузка оборвётся, не выполнится ничего.
main "$@"
exit
