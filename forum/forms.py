from django import forms
from .models import Topic, Post

class TopicForm(forms.ModelForm):
    content = forms.CharField(
        label='Сообщение',
        widget=forms.Textarea(attrs={'rows': 10, 'class': 'form-control'}),
        required=True
    )
    
    class Meta:
        model = Topic
        fields = ['title']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Название темы'}),
        }

class PostForm(forms.ModelForm):
    content = forms.CharField(
        label='Ваш ответ',
        widget=forms.Textarea(attrs={'rows': 8, 'class': 'form-control', 'placeholder': 'Напишите ваш ответ здесь...'}),
        required=True
    )
    
    class Meta:
        model = Post
        fields = ['content']
