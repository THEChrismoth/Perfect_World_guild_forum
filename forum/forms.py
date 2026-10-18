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

class TopicEditForm(forms.ModelForm):
    """Редактирование темы: меняется только название, текст правится в самом посте"""

    class Meta:
        model = Topic
        fields = ['title']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Название темы'}),
        }


MAX_IMAGES_PER_POST = 10
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 МБ


def validate_post_images(files):
    """Проверяет загруженные к посту файлы: количество, размер и что это действительно картинки.
    Возвращает список ошибок (пустой, если всё хорошо)."""
    if len(files) > MAX_IMAGES_PER_POST:
        return [f'Можно прикрепить не больше {MAX_IMAGES_PER_POST} изображений']

    errors = []
    image_field = forms.ImageField()
    for file in files:
        if file.size > MAX_IMAGE_SIZE:
            errors.append(f'Файл «{file.name}» больше {MAX_IMAGE_SIZE // (1024 * 1024)} МБ')
            continue
        try:
            image_field.clean(file)
        except forms.ValidationError:
            errors.append(f'Файл «{file.name}» не является изображением')
    return errors


class PostForm(forms.ModelForm):
    content = forms.CharField(
        label='Ваш ответ',
        widget=forms.Textarea(attrs={'rows': 8, 'class': 'form-control', 'placeholder': 'Напишите ваш ответ здесь...'}),
        required=True
    )
    
    class Meta:
        model = Post
        fields = ['content']
    
    def clean(self):
        cleaned_data = super().clean()
        content = cleaned_data.get('content')
        
        # Проверяем, что текст сообщения заполнен
        if not content:
            raise forms.ValidationError('Заполните текст сообщения')
        
        return cleaned_data
