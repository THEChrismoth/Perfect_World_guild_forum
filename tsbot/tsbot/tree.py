"""Дерево каналов TeamSpeak: пути каналов и поиск канала по пути.

Путь записывается через « / »: «Гильдия / Комнаты членов гильдии». Имена каналов сами могут
содержать «/» («МТВ / ГВГ»), поэтому пути сравниваются целиком, как строки, после нормализации
пробелов — так же, как на сайте (teamspeak/attendance.py).
"""


def normalize(path_text):
    return ' / '.join(part.strip() for part in path_text.split('/') if part.strip())


def channel_paths(channels):
    """channellist -> {cid: ['Гильдия', 'МТВ / ГВГ', 'Пати 1']}"""
    by_id = {c['cid']: c for c in channels}
    paths = {}

    def path_of(cid, seen=()):
        if cid in paths:
            return paths[cid]
        channel = by_id.get(cid)
        if channel is None or cid in seen:
            return []
        parent = channel.get('pid', '0')
        prefix = path_of(parent, seen + (cid,)) if parent not in ('0', '', None) else []
        paths[cid] = prefix + [channel['channel_name']]
        return paths[cid]

    for cid in by_id:
        path_of(cid)
    return paths


def find_channel(channels, path_text):
    """cid канала по пути или None"""
    wanted = normalize(path_text)
    for cid, path in channel_paths(channels).items():
        if normalize(' / '.join(path)) == wanted:
            return cid
    return None
