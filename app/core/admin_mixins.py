"""Общие куски для форм админ-панели."""
from django.contrib.admin.widgets import RelatedFieldWidgetWrapper
from django.urls import reverse
from django.utils.html import format_html


class NoRelatedPopupsMixin:
    """Убирает у полей-ссылок кнопки «+», «изменить», «посмотреть» и «удалить».

    Django открывает по ним форму связанной записи в отдельном окне браузера. Вместо этого
    в подсказке к полю даём ссылку на нужный раздел (см. related_hint).
    Подходит и для ModelAdmin, и для inline.
    """

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        formfield = super().formfield_for_dbfield(db_field, request, **kwargs)
        if formfield and isinstance(formfield.widget, RelatedFieldWidgetWrapper):
            widget = formfield.widget
            widget.can_add_related = widget.can_change_related = False
            widget.can_view_related = widget.can_delete_related = False
        return formfield


def related_hint(text, url_name, link_text):
    """Подсказка к полю со ссылкой на раздел, где создаются связанные записи."""
    return format_html('{} <a href="{}" target="_blank" rel="noopener">{} →</a>', text, reverse(url_name), link_text)
