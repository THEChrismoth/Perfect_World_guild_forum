from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Prefetch
from uuslug import uuslug
from .models import Category, SubCategory, Topic, Post, PostImage
from .forms import TopicForm, TopicEditForm, PostForm, validate_post_images, MAX_IMAGES_PER_POST


def _subcategory_item(subcategory, topics_count, posts_count, last_post=None):
    return {
        'subcategory': subcategory,
        'topics_count': topics_count,
        'posts_count': posts_count,
        'slug': subcategory.slug,
        'title': subcategory.title,
        'last_post': last_post,
        'order': subcategory.order,
    }


def _last_post(subcategory):
    """Последний пост в самой свежей теме подкатегории."""
    return Post.objects.filter(
        topic__subcategory=subcategory
    ).select_related('author__profile', 'topic').order_by('-topic__updated_at', '-created_at').first()


def forum_view(request):
    # Одним набором запросов загружаем категории, подкатегории, группы доступа и счетчики.
    subcategories_qs = SubCategory.objects.prefetch_related('view_groups').annotate(
        topics_num=Count('topics', distinct=True),
        posts_num=Count('topics__posts', distinct=True),
    )
    all_categories = Category.objects.prefetch_related(
        'view_groups',
        Prefetch('subcategories', queryset=subcategories_qs),
    )

    # Фильтруем только те категории, которые видит пользователь.
    categories = []
    for category in all_categories:
        if not category.is_visible_to_user(request.user):
            continue

        # Для каждой категории фильтруем подкатегории.
        visible_subcategories = []
        for subcategory in category.subcategories.all():
            # Категория уже загружена, не запрашиваем ее повторно.
            subcategory.category = category
            if not subcategory.is_visible_to_user(request.user):
                continue

            # Аукцион, ивенты и заявки — отдельные разделы в меню слева, в форуме только темы для общения.
            last_post = _last_post(subcategory) if subcategory.topics_num else None
            visible_subcategories.append(_subcategory_item(
                subcategory, subcategory.topics_num, subcategory.posts_num, last_post=last_post
            ))

        visible_subcategories.sort(key=lambda x: (x.get('order', 0), x['title']))

        # Добавляем категорию только если есть видимые подкатегории.
        if visible_subcategories:
            categories.append({
                'category': category,
                'subcategories': visible_subcategories
            })

    return render(request, 'forum/forum_index.html', {'categories': categories})


def subcategory_detail(request, slug):
    subcategory = get_object_or_404(SubCategory, slug=slug)

    # Проверяем доступ к подкатегории.
    if not subcategory.is_visible_to_user(request.user):
        raise PermissionDenied("У вас нет доступа к этой подкатегории")

    topics = subcategory.topics.select_related('author__profile').annotate(posts_num=Count('posts'))
    context = {'subcategory': subcategory, 'topics': topics}
    return render(request, 'forum/subcategory_detail.html', context)


def _save_post_images(post, files):
    for image in files:
        PostImage.objects.create(post=post, image=image)


@login_required
def topic_create(request, slug):
    subcategory = get_object_or_404(SubCategory, slug=slug)

    # Проверяем доступ к подкатегории.
    if not subcategory.is_visible_to_user(request.user):
        raise PermissionDenied("У вас нет доступа к этой подкатегории")

    if request.method == 'POST':
        form = TopicForm(request.POST)
        images = request.FILES.getlist('images')
        image_errors = validate_post_images(images)
        for error in image_errors:
            messages.error(request, error)

        if form.is_valid() and not image_errors:
            topic = form.save(commit=False)
            topic.author = request.user
            topic.subcategory = subcategory
            topic.save()

            # Создаем пост.
            post = Post.objects.create(
                content=form.cleaned_data['content'],
                author=request.user,
                topic=topic
            )

            # Сохраняем все загруженные изображения.
            _save_post_images(post, images)

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

    # Проверяем доступ к подкатегории темы.
    if not topic.subcategory.is_visible_to_user(request.user):
        raise PermissionDenied("У вас нет доступа к этой теме")

    posts = topic.posts.select_related('author__profile').prefetch_related('images')
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

    # Проверяем доступ к подкатегории.
    if not topic.subcategory.is_visible_to_user(request.user):
        raise PermissionDenied("У вас нет доступа к этой теме")

    if request.user != topic.author and not request.user.is_superuser:
        raise PermissionDenied("У вас нет прав на редактирование этой темы")

    if request.method == 'POST':
        form = TopicEditForm(request.POST, instance=topic)
        if form.is_valid():
            topic = form.save(commit=False)
            if 'title' in form.changed_data:
                # uuslug транслитерирует кириллицу и сам подбирает уникальный slug.
                topic.slug = uuslug(topic.title, instance=topic, max_length=100)
            topic.save()
            messages.success(request, 'Тема успешно отредактирована')
            return redirect('topic_detail', slug=topic.slug)
    else:
        form = TopicEditForm(instance=topic)

    context = {
        'form': form,
        'topic': topic,
    }
    return render(request, 'forum/topic_edit.html', context)


@login_required
def topic_delete(request, slug):
    topic = get_object_or_404(Topic, slug=slug)

    # Проверяем доступ к подкатегории.
    if not topic.subcategory.is_visible_to_user(request.user):
        raise PermissionDenied("У вас нет доступа к этой теме")

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
        images = request.FILES.getlist('images')
        image_errors = validate_post_images(images)
        for error in image_errors:
            messages.error(request, error)

        if form.is_valid() and not image_errors:
            post = form.save(commit=False)
            post.author = request.user
            post.topic = topic
            post.save()

            # Сохраняем все загруженные изображения.
            _save_post_images(post, images)

            messages.success(request, 'Ваш ответ успешно добавлен!')
            return redirect('topic_detail', slug=topic.slug)
        else:
            # Если форма не валидна, показываем ошибки.
            messages.error(request, 'Пожалуйста, исправьте ошибки в форме.')
            posts = topic.posts.select_related('author__profile').prefetch_related('images')
            context = {
                'topic': topic,
                'posts': posts,
                'form': form,
            }
            return render(request, 'forum/topic_detail.html', context)

    # Если GET запрос — редирект на страницу темы.
    return redirect('topic_detail', slug=topic.slug)


@login_required
def post_edit(request, post_id):
    post = get_object_or_404(Post, id=post_id)

    # Проверяем доступ к подкатегории.
    if not post.topic.subcategory.is_visible_to_user(request.user):
        raise PermissionDenied("У вас нет доступа к этому сообщению")

    if request.user != post.author and not request.user.is_superuser:
        raise PermissionDenied("У вас нет прав на редактирование этого сообщения")

    if request.method == 'POST':
        delete_images = [image_id for image_id in request.POST.getlist('delete_images') if image_id.isdigit()]
        images_to_delete = PostImage.objects.filter(id__in=delete_images, post=post)

        new_images = request.FILES.getlist('new_images')
        image_errors = validate_post_images(new_images)
        remaining_images = post.images.count() - images_to_delete.count()
        if not image_errors and remaining_images + len(new_images) > MAX_IMAGES_PER_POST:
            image_errors = [f'Можно прикрепить не больше {MAX_IMAGES_PER_POST} изображений']
        if image_errors:
            for error in image_errors:
                messages.error(request, error)
            return redirect('topic_detail', slug=post.topic.slug)

        content = request.POST.get('content')

        if content is not None:
            post.content = content

        # Обработка удаления изображений.
        for image in images_to_delete:
            image.image.delete(save=False)
            image.delete()

        # Добавление новых изображений.
        _save_post_images(post, new_images)

        post.save()
        messages.success(request, 'Сообщение успешно отредактировано')

    return redirect('topic_detail', slug=post.topic.slug)


@login_required
def post_delete(request, post_id):
    post = get_object_or_404(Post, id=post_id)

    # Проверяем доступ к подкатегории.
    if not post.topic.subcategory.is_visible_to_user(request.user):
        raise PermissionDenied("У вас нет доступа к этому сообщению")

    if request.user != post.author and not request.user.is_superuser:
        raise PermissionDenied("У вас нет прав на удаление этого сообщения")

    if request.method == 'POST':
        topic_slug = post.topic.slug
        post.delete()
        messages.success(request, 'Сообщение успешно удалено')
        return redirect('topic_detail', slug=topic_slug)

    return redirect('topic_detail', slug=post.topic.slug)
