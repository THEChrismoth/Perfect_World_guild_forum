from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q

from core.roles import GUILD_GROUP


class StartForm(forms.Form):
    title = forms.CharField(label='Название (необязательно)', max_length=120, required=False,
                            widget=forms.TextInput(attrs={'class': 'ui-input', 'placeholder': 'Название по дате и времени'}))


class JoinForm(forms.Form):
    code = forms.RegexField(r'^[0-9]{4}$', label='Код замеса', max_length=4, min_length=4,
        error_messages={'invalid': 'Введите четыре цифры.'},
        widget=forms.TextInput(attrs={'class': 'ui-input sk-code-input', 'inputmode': 'numeric',
                                     'pattern': '[0-9]{4}', 'placeholder': '0000', 'autocomplete': 'off'}))


class CorrectionForm(forms.Form):
    user = forms.ModelChoiceField(label='Игрок', queryset=get_user_model().objects.none())
    result = forms.ChoiceField(label='Результат', choices=[
        ('yes', 'Участвовал'), ('no', 'Не участвовал'), ('auto', 'По данным TS')])
    reason = forms.CharField(label='Причина решения', max_length=500,
                             widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, skirmish, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['user'].queryset = get_user_model().objects.filter(
            Q(is_active=True, groups__name=GUILD_GROUP) | Q(skirmish_participations__skirmish=skirmish)
        ).distinct().order_by('username')
        for field in self.fields.values():
            field.widget.attrs['class'] = 'ui-input'
