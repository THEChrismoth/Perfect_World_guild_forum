from django.contrib import admin
from .models import Category, Forum, Topic, Post


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'created_at']
    search_fields = ['name']


@admin.register(Forum)
class ForumAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'created_at']
    list_filter = ['category']
    search_fields = ['name']


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ['title', 'forum', 'author', 'is_pinned', 'is_closed', 'posts_count', 'created_at']
    list_filter = ['forum', 'is_pinned', 'is_closed']
    search_fields = ['title', 'content']
    raw_id_fields = ['author']


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ['id', 'topic', 'author', 'created_at']
    list_filter = ['topic__forum']
    search_fields = ['content']
    raw_id_fields = ['author']
