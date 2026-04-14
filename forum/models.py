from django.db import models
from django.contrib.auth.models import User, Group
from django.utils.text import slugify

class Category(models.Model):
    title = models.CharField('Название категории', max_length=100)
    slug = models.SlugField(unique=True)
    # Только для авторизованных пользователей
    require_auth = models.BooleanField(
        'Только для авторизованных',
        default=False,
        help_text='Если включено, категорию видят только авторизованные пользователи'
    )
    # Группы, которые могут видеть эту категорию (пусто = видят все, если require_auth=False)
    view_groups = models.ManyToManyField(
        Group, 
        blank=True, 
        verbose_name='Группы с доступом',
        help_text='Оставьте пустым для доступа всем пользователям (с учетом require_auth)'
    )

    class Meta:
        ordering = ['title']
        verbose_name = 'Категорию'
        verbose_name_plural = 'Категории'

    def __str__(self):
        return self.title
    
    def is_visible_to_user(self, user):
        """Проверяет, видит ли пользователь эту категорию"""
        # Суперпользователь видит всё
        if user.is_superuser:
            return True
        
        # Проверяем require_auth
        if self.require_auth and not user.is_authenticated:
            return False
        
        # Если нет групп с доступом
        if not self.view_groups.exists():
            return True
        
        # Проверяем группы
        if not user.is_authenticated:
            return False
        
        user_groups = user.groups.all()
        return self.view_groups.filter(id__in=user_groups).exists()

class SubCategory(models.Model):
    title = models.CharField('Название подкатегории', max_length=100)
    slug = models.SlugField(unique=True)
    category = models.ForeignKey(
        Category, 
        on_delete=models.CASCADE,
        related_name='subcategories',
        verbose_name='Категория'
    )
    # Только для авторизованных пользователей
    require_auth = models.BooleanField(
        'Только для авторизованных',
        default=False,
        help_text='Если включено, подкатегорию видят только авторизованные пользователи'
    )
    # Группы, которые могут видеть эту подкатегорию
    view_groups = models.ManyToManyField(
        Group, 
        blank=True, 
        verbose_name='Группы с доступом',
        help_text='Оставьте пустым для доступа всем пользователям (с учетом require_auth)'
    )

    class Meta:
        verbose_name = 'Подкатегорию'
        verbose_name_plural = 'Подкатегории'
        ordering = ['category', 'title']

    def __str__(self):
        return f"{self.title} ({self.category.title})"
    
    def is_visible_to_user(self, user):
        """Проверяет, видит ли пользователь эту подкатегорию"""
        # Сначала проверяем видимость родительской категории
        if not self.category.is_visible_to_user(user):
            return False
        
        # Суперпользователь видит всё
        if user.is_superuser:
            return True
        
        # Проверяем require_auth
        if self.require_auth and not user.is_authenticated:
            return False
        
        # Если нет групп с доступом
        if not self.view_groups.exists():
            return True
        
        # Проверяем группы
        if not user.is_authenticated:
            return False
        
        user_groups = user.groups.all()
        return self.view_groups.filter(id__in=user_groups).exists()
    
    def topics_count(self):
        return self.topics.count()
    
    def posts_count(self):
        return Post.objects.filter(topic__subcategory=self).count()
    
    def last_post(self):
        return Post.objects.filter(topic__subcategory=self).order_by('-created_at').first()

class Topic(models.Model):
    title = models.CharField('Название темы', max_length=100)
    slug = models.SlugField(unique=True, blank=True)
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='topics')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    subcategory = models.ForeignKey(
        SubCategory, 
        on_delete=models.CASCADE,
        related_name='topics',
        verbose_name='Подкатегории'
    )

    class Meta:
        ordering = ['-updated_at']
        verbose_name = 'Тему'
        verbose_name_plural = 'Темы'

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title)
            slug = base_slug
            counter = 1
            
            while Topic.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title
    
    def posts_count(self):
        return self.posts.count()
    
    def last_post(self):
        return self.posts.order_by('-created_at').first()

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
