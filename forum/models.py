from django.db import models
from django.contrib.auth.models import User
from django.utils.text import slugify

class Category(models.Model):
    title = models.CharField('Название категории', max_length = 100)
    slug = models.SlugField(unique = True)

    class Meta:
        ordering = ['title',]
        verbose_name = 'Категорию'
        verbose_name_plural = 'Категории'

    def __str__(self):
        return self.title

class SubCategory(models.Model):
    title = models.CharField('Название подкатегории', max_length = 100)
    slug = models.SlugField(unique = True)
    category = models.ForeignKey(
        Category, 
        on_delete=models.CASCADE,
        related_name='subcategories',
        verbose_name='Категория'
    )

    class Meta:
        verbose_name = 'Подкатегорию'
        verbose_name_plural = 'Подкатегории'
        ordering = ['category', 'title']

    def __str__(self):
        return f"{self.title} ({self.category.title})"

class Topic(models.Model):
    title = models.CharField('Название темы', max_length = 100)
    slug = models.SlugField(unique = True)
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='threads')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    subcategory = models.ForeignKey(
        SubCategory, 
        on_delete=models.CASCADE,
        related_name='topics',
        verbose_name='подкатеории'
    )

    class Meta:
        ordering = ['-updated_at']
        verbose_name = 'Тему'
        verbose_name_plural = 'темы'

    def save(self, *args, **kwargs):
        if not self.slug:
            # Генерируем базовый slug
            base_slug = slugify(self.title)
            slug = base_slug
            counter = 1
            
            # Проверяем уникальность и добавляем номер если нужно
            while Topic.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title

class Post(models.Model):
    content = models.TextField('Содержание')
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='posts')
    topic = models.ForeignKey(
        Topic, 
        on_delete=models.CASCADE,
        related_name='posts',
        verbose_name='Тема'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['created_at']
        verbose_name = 'Пост'
        verbose_name_plural = 'Посты'

    def __str__(self):
        return f"Пост от {self.author.username} в теме {self.topic.title}"
