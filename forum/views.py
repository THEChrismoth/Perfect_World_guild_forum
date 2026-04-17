from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from django.utils.text import slugify
from .models import Category, SubCategory, Topic, Post, PostImage, get_online_users, get_forum_stats, get_latest_posts
from .forms import TopicForm, PostForm
from auction.models import AuctionLot

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
                    # Проверка на аукцион
                    if subcategory.is_auction:
                        from auction.models import AuctionLot
                        visible_subcategories.append({
                            'subcategory': subcategory,
                            'is_auction': True,
                            'is_reception': False,
                            'is_reception_view': False,
                            'topics_count': AuctionLot.objects.filter(status='active').count(),
                            'posts_count': AuctionLot.objects.count(),
                            'slug': subcategory.slug,
                            'title': subcategory.title,
                        })
                    # Проверка на прием заявок (подача) - скрываем для членов гильдии
                    elif subcategory.is_reception:
                        from reception.views import check_guild_member
                        # Члены гильдии не видят подкатегорию подачи заявок
                        if check_guild_member(request.user):
                            continue
                        
                        from reception.models import Application
                        visible_subcategories.append({
                            'subcategory': subcategory,
                            'is_auction': False,
                            'is_reception': True,
                            'is_reception_view': False,
                            'topics_count': 0,
                            'posts_count': 0,
                            'slug': subcategory.slug,
                            'title': subcategory.title,
                        })
                    # Проверка на просмотр заявок (только для членов гильдии)
                    elif subcategory.is_reception_view:
                        from reception.views import check_guild_member
                        if check_guild_member(request.user) or request.user.is_superuser:
                            from reception.models import Application
                            applications_voting = Application.objects.filter(status='voting').count()
                            applications_total = Application.objects.count()
                            visible_subcategories.append({
                                'subcategory': subcategory,
                                'is_auction': False,
                                'is_reception': False,
                                'is_reception_view': True,
                                'topics_count': applications_voting,
                                'posts_count': applications_total,
                                'slug': subcategory.slug,
                                'title': subcategory.title,
                            })
                    else:
                        topics_count = subcategory.topics.count()
                        posts_count = Post.objects.filter(topic__subcategory=subcategory).count()
                        
                        visible_subcategories.append({
                            'subcategory': subcategory,
                            'is_auction': False,
                            'is_reception': False,
                            'is_reception_view': False,
                            'topics_count': topics_count,
                            'posts_count': posts_count,
                            'slug': subcategory.slug,
                            'title': subcategory.title,
                        })
            # Добавляем категорию только если есть видимые подкатегории
            if visible_subcategories:
                categories.append({
                    'category': category,
                    'subcategories': visible_subcategories
                })
    
    # Получаем данные для правого блока
    latest_posts = get_latest_posts(10)
    online_users = get_online_users()
    forum_stats = get_forum_stats()
    
    context = {
        'categories': categories,
        'latest_posts': latest_posts,
        'online_users': online_users,
        'forum_stats': forum_stats,
    }
    return render(request, 'forum/forum_index.html', context)


def subcategory_detail(request, slug):
    subcategory = get_object_or_404(SubCategory, slug=slug)
    
    # Проверяем доступ к подкатегории
    if not subcategory.is_visible_to_user(request.user):
        raise PermissionDenied("У вас нет доступа к этой подкатегории")
    
    # Проверка на аукцион
    if subcategory.is_auction:
        from auction.views import check_auction_access
        if not check_auction_access(request.user):
            raise PermissionDenied("У вас нет доступа к аукциону")
        from django.urls import reverse
        return redirect(reverse('auction:auction_index'))
    
    # Проверка на прием заявок (подача)
    if subcategory.is_reception:
        from django.urls import reverse
        return redirect(reverse('reception:application_form'))
    
    # Проверка на просмотр заявок (голосование)
    if subcategory.is_reception_view:
        from reception.views import check_guild_member
        if not check_guild_member(request.user) and not request.user.is_superuser:
            raise PermissionDenied("Только члены гильдии могут просматривать заявки")
        from django.urls import reverse
        return redirect(reverse('reception:application_list'))
    
    context = {'subcategory': subcategory}
    return render(request, 'forum/subcategory_detail.html', context)


@login_required
def topic_create(request, slug):
    subcategory = get_object_or_404(SubCategory, slug=slug)
    
    # Проверяем доступ к подкатегории
    if not subcategory.is_visible_to_user(request.user):
        raise PermissionDenied("У вас нет доступа к этой подкатегории")
    
    # Проверяем по флагу is_auction
    if subcategory.is_auction:
        return redirect('auction:auction_index')
    
    if request.method == 'POST':
        form = TopicForm(request.POST)
        if form.is_valid():
            topic = form.save(commit=False)
            topic.author = request.user
            topic.subcategory = subcategory
            topic.save()
            
            # Создаем пост
            post = Post.objects.create(
                content=form.cleaned_data['content'],
                author=request.user,
                topic=topic
            )
            
            # Сохраняем все загруженные изображения
            images = request.FILES.getlist('images')
            for image in images:
                PostImage.objects.create(post=post, image=image)
            
            messages.success(request, 'Тема успешно создана!')
            return redirect('topic_detail', slug=topic.slug)
        else:
            messages.error(request, 'Пожалуйста, исправьте ошибки в форме.')
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
            
            # Сохраняем все загруженные изображения
            images = request.FILES.getlist('images')
            for image in images:
                PostImage.objects.create(post=post, image=image)
            
            messages.success(request, 'Ваш ответ успешно добавлен!')
            return redirect('topic_detail', slug=topic.slug)
        else:
            # Если форма не валидна, показываем ошибки
            messages.error(request, 'Пожалуйста, исправьте ошибки в форме.')
            posts = topic.posts.all()
            context = {
                'topic': topic,
                'posts': posts,
                'form': form,
            }
            return render(request, 'forum/topic_detail.html', context)
    
    # Если GET запрос - редирект на страницу темы
    return redirect('topic_detail', slug=topic.slug)


@login_required
def post_edit(request, post_id):
    post = get_object_or_404(Post, id=post_id)
    
    if request.user != post.author and not request.user.is_superuser:
        raise PermissionDenied("У вас нет прав на редактирование этого сообщения")
    
    if request.method == 'POST':
        content = request.POST.get('content')
        
        if content is not None:
            post.content = content
        
        # Обработка удаления изображений
        delete_images = request.POST.getlist('delete_images')
        for image_id in delete_images:
            try:
                image = PostImage.objects.get(id=image_id, post=post)
                image.image.delete(save=False)
                image.delete()
            except PostImage.DoesNotExist:
                pass
        
        # Добавление новых изображений
        new_images = request.FILES.getlist('new_images')
        for image in new_images:
            PostImage.objects.create(post=post, image=image)
        
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
