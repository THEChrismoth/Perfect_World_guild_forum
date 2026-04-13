from django.db import models
from django.forms import CharField

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

