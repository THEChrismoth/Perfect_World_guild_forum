from django.contrib.staticfiles.storage import ManifestStaticFilesStorage, StaticFilesStorage


class ForgivingManifestStaticFilesStorage(ManifestStaticFilesStorage):
    """Статика с хэшем содержимого в имени: style.css -> style.3f2a9c1b7d4e.css.

    После обновления сайта у файла меняется имя, и браузер сразу загружает новую версию,
    хотя Caddy разрешает кэшировать статику надолго.

    Если файла нет (например, иконки лотов ещё не загружены), обычный ManifestStaticFilesStorage
    роняет страницу с ошибкой 500. Здесь вместо этого отдаётся ссылка без хэша — как раньше.
    """

    manifest_strict = False

    def url(self, name, force=False):
        try:
            return super().url(name, force)
        except ValueError:
            return StaticFilesStorage.url(self, name)

    def url_converter(self, name, hashed_files, template=None):
        """Оставляет как есть ссылки на несуществующие файлы внутри CSS/JS.

        При collectstatic ссылки внутри CSS/JS заменяются на имена с хэшем. Сторонние пакеты
        иногда ссылаются на файлы, которых нет (например, на карты исходников *.js.map),
        и collectstatic падал бы при старте контейнера.
        """
        convert = super().url_converter(name, hashed_files, template)

        def safe_convert(matchobj):
            try:
                return convert(matchobj)
            except ValueError:
                return matchobj['matched']

        return safe_convert
