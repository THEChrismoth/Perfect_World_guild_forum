import uuid

from django import forms


class MessageForm(forms.Form):
    body = forms.CharField(
        label='Сообщение',
        max_length=4000,
        strip=False,
        widget=forms.Textarea(
            attrs={
                'class': 'ui-input pm-textarea',
                'rows': 3,
                'placeholder': 'Напишите сообщение…',
                'maxlength': 4000,
            }
        ),
    )
    client_id = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        initial = kwargs.setdefault('initial', {})
        initial.setdefault('client_id', uuid.uuid4())
        super().__init__(*args, **kwargs)
