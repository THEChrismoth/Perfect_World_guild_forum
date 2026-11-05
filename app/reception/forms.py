from django import forms
from .models import Application

class ApplicationForm(forms.ModelForm):
    """Форма подачи заявки.

    Класс персонажа и характеристики не вводятся заново — они берутся из профиля.
    """

    class Meta:
        model = Application
        fields = [
            'previous_nicknames',
            'on_blacklist', 'blacklist_details', 'other_guilds',
            'development_plans', 'guarantors',
            'screenshot1', 'screenshot2', 'screenshot3', 'screenshot4', 'screenshot5',
        ]
        widgets = {
            'previous_nicknames': forms.Textarea(attrs={
                'rows': 2,
                'placeholder': 'Например: xX_Player_Xx, OldNick'
            }),
            'blacklist_details': forms.Textarea(attrs={
                'rows': 2,
                'placeholder': 'Если вы в ЧС, укажите причину'
            }),
            'other_guilds': forms.Textarea(attrs={
                'rows': 2,
                'placeholder': 'Перечислите все гильдии'
            }),
            'development_plans': forms.Textarea(attrs={
                'rows': 4,
                'placeholder': 'Опишите свои планы на развитие...'
            }),
            'guarantors': forms.Textarea(attrs={
                'rows': 2,
                'placeholder': 'Никнеймы поручителей'
            }),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user:
            instance.user = self.user
            profile = getattr(self.user, 'profile', None)
            # Класс — снимок на момент подачи: если игрок потом сменит его в профиле, в заявке останется прежний.
            if profile and profile.player_class:
                instance.player_class = profile.get_player_class_display()
        if commit:
            instance.save()
        return instance

