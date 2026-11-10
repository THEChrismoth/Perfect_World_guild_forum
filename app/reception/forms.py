from django import forms
from .models import Application

class ApplicationForm(forms.ModelForm):
    """Форма подачи заявки.

    Класс персонажа и характеристики не вводятся заново — они берутся из профиля.
    """

    class Meta:
        model = Application
        fields = ['development_plans', 'screenshot_pa', 'screenshot_pz']
        widgets = {
            'development_plans': forms.Textarea(attrs={
                'rows': 4,
                'placeholder': 'Опишите свои планы на развитие...'
            }),
            'screenshot_pa': forms.FileInput(attrs={'accept': 'image/*'}),
            'screenshot_pz': forms.FileInput(attrs={'accept': 'image/*'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        # Скриншот нужен для каждого заполненного сета: по нему администратор сверяет статы.
        sets = {gear.kind: gear for gear in self.user.gear_sets.all()} if self.user else {}
        self.fields['screenshot_pa'].required = True
        self.fields['screenshot_pz'].required = 'pz' in sets and not sets['pz'].is_empty()
        for kind, name in (('pa', 'ПА'), ('pz', 'ПЗ')):
            self.fields[f'screenshot_{kind}'].error_messages['required'] = (
                f'Прикрепите скриншот окна характеристик в сете {name} — по нему администратор сверит статы'
            )

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

