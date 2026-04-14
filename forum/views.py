from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from .models import Category, SubCategory, Topic, Post
from .forms import TopicForm, PostForm

def forum_view(request):
    # Получаем все категории
    all_categories = Category.objects.all()
    # Фильтруем только те, которые видит пользователь
    categories = []
    for category in all_categories:
        if category.is_visible_to_user(request.user):
            # Для каждой категории фильтруем подкатегории
            visible_subcategories = []
            for subcategory in category.subcategories.all():
                if subcategory.is_visible_to_user(request.user):
                    visible_subcategories.append(subcategory)
            # Добавляем категорию только если есть видимые подкатегории
            if visible_subcategories:
                categories.append({
                    'category': category,
                    'subcategories': visible_subcategories
                })
    
    context = {
        'categories': categories,
    }
    return render(request, 'forum/forum_index.html', context)

def subcategory_detail(request, slug):
    subcategory = get_object_or_404(SubCategory, slug=slug)
    
    # Проверяем доступ к подкатегории
    if not subcategory.is_visible_to_user(request.user):
        raise PermissionDenied("У вас нет доступа к этой подкатегории")
    
    context = {'subcategory': subcategory}
    return render(request, 'forum/subcategory_detail.html', context)

@login_required
def topic_create(request, slug):
    subcategory = get_object_or_404(SubCategory, slug=slug)
    
    # Проверяем доступ к подкатегории
    if not subcategory.is_visible_to_user(request.user):
        raise PermissionDenied("У вас нет доступа к этой подкатегории")
    
    if request.method == 'POST':
        form = TopicForm(request.POST)
        if form.is_valid():
            topic = form.save(commit=False)
            topic.author = request.user
            topic.subcategory = subcategory
            topic.save()
            
            Post.objects.create(
                content=form.cleaned_data['content'],
                author=request.user,
                topic=topic
            )
            
            return redirect('topic_detail', slug=topic.slug)
    else:
        form = TopicForm()
    
    context = {
        'form': form,
        'subcategory': subcategory,
    }
    return render(request, 'forum/topic_form.html', context)

def topic_detail(request, slug):
    topic = get_object_or_404(Topic, slug=slug)
    
    # Проверяем доступ к подкатегории темы
    if not topic.subcategory.is_visible_to_user(request.user):
        raise PermissionDenied("У вас нет доступа к этой теме")
    
    posts = topic.posts.all()
    form = PostForm()
    context = {
        'topic': topic,
        'posts': posts,
        'form': form,
    }
    return render(request, 'forum/topic_detail.html', context)

@login_required
def topic_edit(request, slug):
    topic = get_object_or_404(Topic, slug=slug)
    
    if request.user != topic.author and not request.user.is_superuser:
        raise PermissionDenied("У вас нет прав на редактирование этой темы")
    
    if request.method == 'POST':
        form = TopicForm(request.POST, instance=topic)
        if form.is_valid():
            topic = form.save(commit=False)
            if 'title' in form.changed_data:
                base_slug = slugify(topic.title)
                new_slug = base_slug
                counter = 1
                while Topic.objects.filter(slug=new_slug).exclude(id=topic.id).exists():
                    new_slug = f"{base_slug}-{counter}"
                    counter += 1
                topic.slug = new_slug
            topic.save()
            messages.success(request, 'Тема успешно отредактирована')
            return redirect('topic_detail', slug=topic.slug)
    else:
        form = TopicForm(instance=topic)
    
    context = {
        'form': form,
        'topic': topic,
    }
    return render(request, 'forum/topic_edit.html', context)

@login_required
def topic_delete(request, slug):
    topic = get_object_or_404(Topic, slug=slug)
    
    if request.user != topic.author and not request.user.is_superuser:
        raise PermissionDenied("У вас нет прав на удаление этой темы")
    
    if request.method == 'POST':
        subcategory_slug = topic.subcategory.slug
        topic_title = topic.title
        topic.delete()
        messages.success(request, f'Тема "{topic_title}" успешно удалена')
        return redirect('subcategory_detail', slug=subcategory_slug)
    
    context = {
        'topic': topic,
    }
    return render(request, 'forum/topic_confirm_delete.html', context)

@login_required
def post_create(request, slug):
    topic = get_object_or_404(Topic, slug=slug)
    
    if not topic.subcategory.is_visible_to_user(request.user):
        raise PermissionDenied("У вас нет доступа к этой теме")
    
    if request.method == 'POST':
        form = PostForm(request.POST)
        if form.is_valid():
            post = form.save(commit=False)
            post.author = request.user
            post.topic = topic
            post.save()
            
            messages.success(request, 'Ваш ответ успешно добавлен!')
            return redirect('topic_detail', slug=topic.slug)
    else:
        return redirect('topic_detail', slug=topic.slug)

@login_required
def post_edit(request, post_id):
    post = get_object_or_404(Post, id=post_id)
    
    if request.user != post.author and not request.user.is_superuser:
        raise PermissionDenied("У вас нет прав на редактирование этого сообщения")
    
    if request.method == 'POST':
        content = request.POST.get('content')
        if content:
            post.content = content
            post.save()
            messages.success(request, 'Сообщение успешно отредактировано')
    
    return redirect('topic_detail', slug=post.topic.slug)

@login_required
def post_delete(request, post_id):
    post = get_object_or_404(Post, id=post_id)
    
    if request.user != post.author and not request.user.is_superuser:
        raise PermissionDenied("У вас нет прав на удаление этого сообщения")
    
    if request.method == 'POST':
        topic_slug = post.topic.slug
        post.delete()
        messages.success(request, 'Сообщение успешно удалено')
        return redirect('topic_detail', slug=topic_slug)
    
    return redirect('topic_detail', slug=post.topic.slug)
