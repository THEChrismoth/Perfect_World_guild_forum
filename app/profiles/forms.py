import re
from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from core.captcha import TOKEN_FIELD, verify_captcha
from core.models import SiteSettings
from .models import MAGIC_CLASSES, GearSet, Profile, class_icon_url, damage_type

class RegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)
    # Выбирается в списке с иконками (registration/class_picker.html), поэтому без своего виджета.
    player_class = forms.ChoiceField(label='Класс персонажа', choices=Profile.CLASS_CHOICES,
                                     error_messages={'required': 'Выберите класс персонажа'})

    field_order = ['username', 'email', 'player_class', 'password1', 'password2']

    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']

    def __init__(self, *args, **kwargs):
        self.site_settings = kwargs.pop('site_settings', None) or SiteSettings.load()
        super().__init__(*args, **kwargs)

    def class_options(self):
        """Классы для выпадающего списка: значение, название, иконка, выбран ли."""
        selected = self['player_class'].value()
        return [{'value': value, 'label': label, 'icon': class_icon_url(value), 'selected': value == selected}
                for value, label in Profile.CLASS_CHOICES]

    def selected_class(self):
        return next((option for option in self.class_options() if option['selected']), None)

    def save_profile(self, user):
        """Класс хранится в профиле, а профиль появляется только после сохранения пользователя."""
        Profile.objects.filter(user=user).update(player_class=self.cleaned_data['player_class'])

    def clean_email(self):
        email = self.cleaned_data['email']
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Пользователь с такой почтой уже зарегистрирован')
        return email

    def clean(self):
        cleaned_data = super().clean()
        # Капча проверяется последней и только для формы без других ошибок:
        # токен одноразовый, и тратить его на заведомо неверную форму нельзя.
        if self.site_settings.captcha_active and not self.errors:
            error = verify_captcha(self.data.get(TOKEN_FIELD, ''), self.site_settings)
            if error:
                raise forms.ValidationError(error)
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        if commit:
            user.save()
            self.save_profile(user)
        return user

TS3_UID_RE = re.compile(r'^[A-Za-z0-9+/]{27}=$')


class ProfileForm(forms.ModelForm):
    def clean_ts3_id(self):
        """Уникальный ID клиента TeamSpeak: 28 символов, заканчивается на «=».

        Бот ищет игрока по нему, поэтому опечатка сломает выдачу доступа и учёт ивентов.
        """
        value = (self.cleaned_data.get('ts3_id') or '').strip()
        if value and not TS3_UID_RE.match(value):
            raise forms.ValidationError(
                'Это не похоже на TS3 ID. В клиенте TeamSpeak откройте Инструменты → Идентификаторы, выберите '
                'локальный идентификатор (не синхронизированный с myTeamSpeak) и скопируйте «Уникальный ID» — '
                '28 символов, в конце знак «=»'
            )
        return value or None

    class Meta:
        model = Profile
        fields = ['avatar', 'ts3_id', 'player_class', 'main_set']
        widgets = {
            'avatar': forms.ClearableFileInput(attrs={'accept': 'image/*'}),
        }


class GearSetForm(forms.ModelForm):
    """Редактирует атаку и пробив по классу, сохраняя второй тип без изменений."""

    attack = forms.IntegerField(label='Атака', min_value=0, required=False)
    pierce = forms.IntegerField(label='Пробив', min_value=0, required=False)

    class Meta:
        model = GearSet
        fields = tuple(name for name in GearSet.STAT_FIELDS
                       if name not in ('fa', 'ma', 'physical_pierce', 'magic_pierce'))

    STAT_GROUPS = {
        'main': [('HP', 'hp'), ('Боевой дух (БД)', 'bd'), ('Бонус уровня (БУ)', 'bu')],
        'attack': [('Показатель атаки (ПА)', 'pa'), ('Атака', 'attack'), ('Пробив', 'pierce')],
        'defense': [('Показатель защиты (ПЗ)', 'pz'), ('Физ. защита', 'physical_defense'),
                    ('Маг. защита', 'magic_defense')],
    }

    def __init__(self, *args, player_class=None, **kwargs):
        super().__init__(*args, **kwargs)
        if player_class is None and self.instance.user_id:
            player_class = self.instance.user.profile.player_class
        self.damage_type = damage_type(player_class)
        magic = self.damage_type == 'magic'
        for name, physical, magical in [('attack', 'fa', 'ma'), ('pierce', 'physical_pierce', 'magic_pierce')]:
            field = self.fields[name]
            field.label = ('Маг. ' if magic else 'Физ. ') + ('атака' if name == 'attack' else 'пробив')
            self.initial.setdefault(name, getattr(self.instance, magical if magic else physical))
            field.widget.attrs.update({
                'data-damage-stat': name, 'data-damage-type': self.damage_type,
                'data-physical-value': getattr(self.instance, physical),
                'data-magic-value': getattr(self.instance, magical),
                'data-magic-classes': ','.join(sorted(MAGIC_CLASSES)),
            })

    def stat_groups(self):
        return {group: [{'label': self.fields[names[0]].label if names[0] in ('attack', 'pierce') else label,
                         'fields': [self[name] for name in names]} for label, *names in items]
                for group, items in self.STAT_GROUPS.items()}

    def save(self, commit=True):
        magic = self.damage_type == 'magic'
        setattr(self.instance, 'ma' if magic else 'fa', self.cleaned_data['attack'] or 0)
        setattr(self.instance, 'magic_pierce' if magic else 'physical_pierce', self.cleaned_data['pierce'] or 0)
        return super().save(commit=commit)


class UserForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['username']
        labels = {'username': 'Никнейм'}
        help_texts = {'username': 'Буквы, цифры и символы @ . + - _'}
