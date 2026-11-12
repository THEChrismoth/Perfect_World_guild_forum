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
