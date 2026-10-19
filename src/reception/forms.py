from django import forms
from .models import Application

class ApplicationForm(forms.ModelForm):
    """Форма подачи заявки"""
    
    class Meta:
        model = Application
        fields = [
            'previous_nicknames', 'timezone', 'real_name', 'age',
            'on_blacklist', 'blacklist_details', 'other_guilds',
            'development_plans', 'guarantors',
            'screenshot1', 'screenshot2', 'screenshot3', 'screenshot4', 'screenshot5',
        ]
        widgets = {
            'previous_nicknames': forms.Textarea(attrs={
                'rows': 2,
                'placeholder': 'Например: xX_Player_Xx, OldNick',
                'class': 'form-control'
            }),
            'timezone': forms.Select(attrs={'class': 'form-control'}),
            'real_name': forms.TextInput(attrs={
                'placeholder': 'Ваше настоящее имя',
                'class': 'form-control'
            }),
            'age': forms.NumberInput(attrs={
                'placeholder': 'Ваш возраст',
                'class': 'form-control'
            }),
            'blacklist_details': forms.Textarea(attrs={
                'rows': 2,
                'placeholder': 'Если вы в ЧС, укажите причину',
                'class': 'form-control'
            }),
            'other_guilds': forms.Textarea(attrs={
                'rows': 2,
                'placeholder': 'Перечислите все гильдии',
                'class': 'form-control'
            }),
            'development_plans': forms.Textarea(attrs={
                'rows': 4,
                'placeholder': 'Опишите свои планы на развитие...',
                'class': 'form-control'
            }),
            'guarantors': forms.Textarea(attrs={
                'rows': 2,
                'placeholder': 'Никнеймы поручителей',
                'class': 'form-control'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        timezones = [
            ('UTC-12', 'UTC-12:00'), ('UTC-11', 'UTC-11:00'), ('UTC-10', 'UTC-10:00'),
            ('UTC-9', 'UTC-09:00'), ('UTC-8', 'UTC-08:00'), ('UTC-7', 'UTC-07:00'),
            ('UTC-6', 'UTC-06:00'), ('UTC-5', 'UTC-05:00'), ('UTC-4', 'UTC-04:00'),
            ('UTC-3', 'UTC-03:00'), ('UTC-2', 'UTC-02:00'), ('UTC-1', 'UTC-01:00'),
            ('UTC+0', 'UTC±00:00'), ('UTC+1', 'UTC+01:00'), ('UTC+2', 'UTC+02:00'),
            ('UTC+3', 'UTC+03:00'), ('UTC+4', 'UTC+04:00'), ('UTC+5', 'UTC+05:00'),
            ('UTC+6', 'UTC+06:00'), ('UTC+7', 'UTC+07:00'), ('UTC+8', 'UTC+08:00'),
            ('UTC+9', 'UTC+09:00'), ('UTC+10', 'UTC+10:00'), ('UTC+11', 'UTC+11:00'),
            ('UTC+12', 'UTC+12:00'),
        ]
        self.fields['timezone'].widget = forms.Select(choices=timezones)
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user:
            instance.user = self.user
            if hasattr(self.user, 'profile') and self.user.profile.player_class:
                class_display = dict(self.user.profile.CLASS_CHOICES).get(self.user.profile.player_class, '')
                instance.player_class = class_display or self.user.profile.player_class
        if commit:
            instance.save()
        return instance


class VoteForm(forms.Form):
    """Форма голосования"""
    vote = forms.ChoiceField(choices=[
        ('for', 'За'), ('against', 'Против'), ('abstain', 'Воздержался'),
    ], widget=forms.RadioSelect)
    comment = forms.CharField(widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Ваш комментарий'}), required=False)
