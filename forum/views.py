from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Category, SubCategory, Topic, Post
from .forms import TopicForm, PostForm 

def forum_view(request):
    categories = Category.objects.all()
    subcategories = SubCategory.objects.all()

    context = {
            'categories': categories,
            'subcategories': subcategories,
            }

    return render(request, 'forum/forum_index.html', context)

def subcategory_detail(request, slug):
    subcategory = get_object_or_404(SubCategory, slug=slug)
    context = {'subcategory': subcategory}
    return render(request, 'forum/subcategory_detail.html', context)

@login_required
def topic_create(request, slug):
    subcategory = get_object_or_404(SubCategory, slug=slug)

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
    posts = topic.posts.all()
    context = {
        'topic': topic,
        'posts': posts,
    }
    return render(request, 'forum/topic_detail.html', context)

@login_required
def topic_delete(request, slug):
    topic = get_object_or_404(Topic, slug=slug)

    if request.user != topic.author and not request.user.is_superuser:
        raise PermissionDenied("У вас нет прав на удаление этой темы")

    if request.method == 'POST':
        subcategory_slug = topic.subcategory.slug
        topic.delete()
        messages.success(request, f'Тема "{topic.title}" успешно удалена')
        return redirect('subcategory_detail', slug=subcategory_slug)

    context = {
        'topic': topic,
    }
    return render(request, 'forum/topic_confirm_delete.html', context)

@login_required
def post_create(request, slug):
    topic = get_object_or_404(Topic, slug=slug)
    
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
        form = PostForm()
    
    context = {
        'form': form,
        'topic': topic,
    }
    return render(request, 'forum/post_create.html', context)

