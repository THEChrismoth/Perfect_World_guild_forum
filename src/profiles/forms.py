import re
from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from core.captcha import TOKEN_FIELD, verify_captcha
from core.models import SiteSettings
from .models import Profile

class RegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']

    def __init__(self, *args, **kwargs):
        self.site_settings = kwargs.pop('site_settings', None) or SiteSettings.load()
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = self.cleaned_data['email']
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Пользователь с такой почтой уже зарегистрирован')
        return email

    def clean(self):
        cleaned_data = super().clean()
        # Капча проверяется последней и только для формы без других ошибок:
        # токен одноразовый, и тратить его на заведомо неверную форму нельзя
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
        return user

TS3_UID_RE = re.compile(r'^[A-Za-z0-9+/]{27}=$')


class ProfileForm(forms.ModelForm):
    def clean_ts3_id(self):
        """Уникальный ID клиента TeamSpeak: 28 символов, заканчивается на «=».
        Бот ищет игрока по нему, поэтому опечатка сломает выдачу доступа и учёт ивентов"""
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
        fields = [
            'avatar', 'ts3_id', 'real_name', 'birth_date', 'city', 'timezone', 'player_class',
            'hp', 'mp', 'bd',
            'pa', 'fa', 'ma','crit_damage', 'crit_chance', 'bu', 'accuracy',
            'pz', 'physical_defense', 'magic_defense', 'physical_pierce', 'magic_pierce',  'dodge'
        ]
        widgets = {
            'birth_date': forms.DateInput(attrs={'type': 'date'}),
            'avatar': forms.ClearableFileInput(attrs={'accept': 'image/*'}),
        }
        labels = {
            'hp': '❤️ HP',
            'mp': '💧 MP',
            'fa': 'ФА - Физическая атака',
            'ma': 'МА - Магическая атака',
            'pa': 'ПА - Показатель Атаки',
            'pz': 'ПЗ - Прямая защита',
            'bd': 'БД - Боевой дух',
            'bu': 'БУ - Бонус уровня',
            'physical_defense': 'Физическая защита',
            'magic_defense': 'Магическая защита',
            'physical_pierce': 'Физический пробив',
            'magic_pierce': 'Магический пробив',
            'crit_damage': 'Критический урон',
            'crit_chance': 'Критический шанс',
            'accuracy': 'Меткость',
            'dodge': 'Уклонение',
        }

class UserForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['username']
