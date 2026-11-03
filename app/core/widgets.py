from django import forms

DATETIME_LOCAL_FORMAT = '%Y-%m-%dT%H:%M'


class DateTimeLocalInput(forms.DateTimeInput):
    """Дата и время одним полем с календарём браузера вместо двух полей Django «Сегодня | Сейчас».

    quick — быстрые кнопки под полем: [('now', 'Сейчас'), ('+1d', '+1 день'), ...];
    «+N дней» считаются от поля from_field (например, от даты начала), а если оно пустое — от текущего момента.
    Кнопки работают через admin/js/datetime_quick.js.
    """
    input_type = 'datetime-local'
    template_name = 'widgets/datetime_local.html'

    def __init__(self, attrs=None, quick=(), from_field=''):
        super().__init__(attrs=attrs, format=DATETIME_LOCAL_FORMAT)
        self.quick = quick
        self.from_field = from_field

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context['widget'].update(quick=self.quick, from_field=self.from_field)
        return context


def datetime_local_field(**kwargs):
    """Поле формы под DateTimeLocalInput: браузер присылает значение в формате 2026-11-03T14:30."""
    return forms.DateTimeField(input_formats=[DATETIME_LOCAL_FORMAT, '%Y-%m-%dT%H:%M:%S'], **kwargs)
