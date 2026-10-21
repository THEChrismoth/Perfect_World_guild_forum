from django import forms
from .models import Application

class ApplicationForm(forms.ModelForm):
    """Форма подачи заявки.

    Личные данные (имя, возраст, часовой пояс) и класс персонажа не вводятся заново —
    они берутся из профиля в момент подачи, как и характеристики персонажа.
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
                'placeholder': 'Например: xX_Player_Xx, OldNick',
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

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user:
            instance.user = self.user
            profile = getattr(self.user, 'profile', None)
            if profile:
                # Снимок данных профиля на момент подачи: если профиль потом изменится,
                # в заявке останется то, что видели проголосовавшие.
                instance.real_name = profile.real_name
                instance.age = profile.age()
                instance.timezone = profile.timezone
                if profile.player_class:
                    instance.player_class = profile.get_player_class_display()
        if commit:
            instance.save()
        return instance


class VoteForm(forms.Form):
    """Форма голосования."""
    vote = forms.ChoiceField(choices=[
        ('for', 'За'), ('against', 'Против'), ('abstain', 'Воздержался'),
    ], widget=forms.RadioSelect)
    comment = forms.CharField(widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Ваш комментарий'}), required=False)
