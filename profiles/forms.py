from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from django_recaptcha.fields import ReCaptchaField
from .models import Profile

class RegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)
    captcha = ReCaptchaField()
    
    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']
    
    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.is_active = False
        if commit:
            user.save()
        return user

class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = [
            'avatar', 'ts3_id', 'birth_date', 'city', 'player_class',
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
