from django.contrib import admin

from core.admin_mixins import NoRelatedPopupsMixin
from .models import Category, SubCategory, Topic, Post

@admin.register(Category)
class CategoryAdmin(NoRelatedPopupsMixin, admin.ModelAdmin):
    list_display = ('title', 'order', 'slug', 'require_auth')
    prepopulated_fields = {'slug': ('title',)}
    filter_horizontal = ('view_groups',)

@admin.register(SubCategory)
class SubCategoryAdmin(NoRelatedPopupsMixin, admin.ModelAdmin):
    list_display = ('title', 'order', 'slug', 'category', 'require_auth', 'is_auction', 'is_reception', 'is_reception_view')
    list_filter = ('category', 'require_auth', 'is_auction', 'is_reception', 'is_reception_view')
    prepopulated_fields = {'slug': ('title',)}
    filter_horizontal = ('view_groups',)

@admin.register(Topic)
class TopicAdmin(NoRelatedPopupsMixin, admin.ModelAdmin):
    list_display = ('title', 'slug', 'author', 'subcategory', 'created_at')
    prepopulated_fields = {'slug': ('title',)}

@admin.register(Post)
class PostAdmin(NoRelatedPopupsMixin, admin.ModelAdmin):
    list_display = ('author', 'topic', 'created_at')
