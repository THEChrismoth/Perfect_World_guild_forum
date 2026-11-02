from django.contrib import admin

from core.admin_mixins import NoRelatedPopupsMixin
from .models import Category, SubCategory, Topic, Post

@admin.register(Category)
class CategoryAdmin(NoRelatedPopupsMixin, admin.ModelAdmin):
    list_display = ('title', 'order', 'slug')
    prepopulated_fields = {'slug': ('title',)}
    filter_horizontal = ('view_groups',)

@admin.register(SubCategory)
class SubCategoryAdmin(NoRelatedPopupsMixin, admin.ModelAdmin):
    list_display = ('title', 'order', 'slug', 'category')
    list_filter = ('category',)
    prepopulated_fields = {'slug': ('title',)}
    filter_horizontal = ('view_groups',)

@admin.register(Topic)
class TopicAdmin(NoRelatedPopupsMixin, admin.ModelAdmin):
    list_display = ('title', 'slug', 'author', 'subcategory', 'created_at')
    prepopulated_fields = {'slug': ('title',)}

@admin.register(Post)
class PostAdmin(NoRelatedPopupsMixin, admin.ModelAdmin):
    list_display = ('author', 'topic', 'created_at')
