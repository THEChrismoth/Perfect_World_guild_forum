from django import forms
from django.contrib.auth.models import User
from django.db.models import Q

from core.roles import GUILD_GROUP
from .models import Party


class PartyRosterForm(forms.Form):
    leader = forms.ModelChoiceField(label='Лидер', queryset=User.objects.none(), required=False)
    members = forms.ModelMultipleChoiceField(label='Участники', queryset=User.objects.none(), required=False)

    def __init__(self, *args, party, **kwargs):
        super().__init__(*args, **kwargs)
        self.party = party
        current = list(party.members.values_list('user_id', flat=True))
        if party.leader_id:
            current.append(party.leader_id)
        users = User.objects.filter(Q(is_active=True, groups__name=GUILD_GROUP) | Q(pk__in=current)).distinct().order_by('username')
        self.fields['leader'].queryset = users
        self.fields['members'].queryset = users
        self.fields['leader'].widget.attrs['class'] = 'ui-input'
        self.fields['members'].widget.attrs.update({'class': 'ui-input', 'size': 10})
        if not self.is_bound:
            self.initial.update(leader=party.leader_id, members=list(party.members.values_list('user_id', flat=True)))

    def clean(self):
        data = super().clean()
        if self.errors:
            return data
        from .services import validate_roster
        validate_roster(self.party, data['leader'], list(data['members']))
        return data


class InvitationForm(forms.ModelForm):
    class Meta:
        from .models import EventNotification
        model = EventNotification
        fields = ['event_date', 'start_time', 'duration_minutes', 'subject', 'message']
        widgets = {
            'event_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'start_time': forms.TimeInput(attrs={'type': 'time'}, format='%H:%M'),
            'message': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, event_type, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.event_type = event_type
        for field in self.fields.values():
            field.widget.attrs['class'] = 'ui-input'
        self.fields['start_time'].required = True
        self.fields['subject'].help_text = 'Можно оставить пустым — название и дата подставятся автоматически.'

    def clean(self):
        from django.utils import timezone
        data = super().clean()
        day = data.get('event_date')
        if day and day < timezone.localdate():
            self.add_error('event_date', 'Эта дата уже прошла.')
        if day and self._meta.model.objects.filter(event_type=self.instance.event_type, event_date=day).exists():
            self.add_error('event_date', 'На эту дату уже назначен ивент этого типа.')
        if data.get('duration_minutes', 0) < 1:
            self.add_error('duration_minutes', 'Длительность должна быть больше нуля.')
        return data
