from django.contrib import admin
from .models import Category, SubCategory, Topic, Post

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('title', 'slug', 'require_auth')
    prepopulated_fields = {'slug': ('title',)}
    filter_horizontal = ('view_groups',)

@admin.register(SubCategory)
class SubCategoryAdmin(admin.ModelAdmin):
    list_display = ('title', 'slug', 'category', 'require_auth', 'is_auction')
    list_filter = ('category', 'require_auth', 'is_auction')
    prepopulated_fields = {'slug': ('title',)}
    filter_horizontal = ('view_groups',)

@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ('title', 'slug', 'author', 'subcategory', 'created_at')
    prepopulated_fields = {'slug': ('title',)}

@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ('author', 'topic', 'created_at')
