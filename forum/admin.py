from django.contrib import admin
from .models import Category, SubCategory

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['title', 'slug']
    prepopulated_fields = {'slug': ('title',)}
    list_per_page = 10

@admin.register(SubCategory)
class SubCategoryAdmin(admin.ModelAdmin):
    list_display = ['title', 'slug', 'category']
    list_filter = ['category']
    prepopulated_fields = {'slug': ('title',)}
    list_per_page = 10
