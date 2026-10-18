from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Prefetch
from uuslug import uuslug
from .models import Category, SubCategory, Topic, Post, PostImage, get_online_users, get_forum_stats, get_latest_posts
from .forms import TopicForm, TopicEditForm, PostForm, validate_post_images, MAX_IMAGES_PER_POST
from auction.models import AuctionLot
from auction.views import check_auction_access
from reception.models import Application
from reception.views import check_guild_member
from events.models import EventType


def _subcategory_item(subcategory, topics_count, posts_count, is_events=False, is_auction=False,
                      is_reception=False, is_reception_view=False, last_post=None):
    return {
        'subcategory': subcategory,
        'is_events': is_events,
        'is_auction': is_auction,
        'is_reception': is_reception,
        'is_reception_view': is_reception_view,
        'topics_count': topics_count,
        'posts_count': posts_count,
        'slug': subcategory.slug,
        'title': subcategory.title,
        'last_post': last_post,
        'order': subcategory.order,
    }


def _last_post(subcategory):
    """Последний пост в самой свежей теме подкатегории"""
    return Post.objects.filter(
        topic__subcategory=subcategory
    ).select_related('author', 'topic').order_by('-topic__updated_at', '-created_at').first()


def forum_view(request):
    # Одним набором запросов загружаем категории, подкатегории, группы доступа и счетчики
    subcategories_qs = SubCategory.objects.prefetch_related('view_groups').annotate(
        topics_num=Count('topics', distinct=True),
        posts_num=Count('topics__posts', distinct=True),
    )
    all_categories = Category.objects.prefetch_related(
        'view_groups',
        Prefetch('subcategories', queryset=subcategories_qs),
    )

    is_guild_member = check_guild_member(request.user) if request.user.is_authenticated else False
    # Счетчики для специальных подкатегорий считаем лениво и один раз
    special_counts = {}

    def auction_counts():
        if 'auction' not in special_counts:
            special_counts['auction'] = (
                AuctionLot.objects.filter(status='active').count(),
                AuctionLot.objects.count(),
            )
        return special_counts['auction']

    def reception_counts():
        if 'reception' not in special_counts:
            special_counts['reception'] = (
                Application.objects.filter(status='voting').count(),
                Application.objects.count(),
            )
        return special_counts['reception']

    def events_counts(subcategory):
        event_types = EventType.objects.filter(forum_subcategory=subcategory)
        return event_types.filter(is_active=True).count(), event_types.count()

    # Фильтруем только те категории, которые видит пользователь
    categories = []
    for category in all_categories:
        if not category.is_visible_to_user(request.user):
            continue

        # Для каждой категории фильтруем подкатегории
        visible_subcategories = []
        for subcategory in category.subcategories.all():
            # Категория уже загружена, не запрашиваем ее повторно
            subcategory.category = category
            if not subcategory.is_visible_to_user(request.user):
                continue

            # Проверка на ивентовую подкатегорию
            if subcategory.is_events:
                visible_subcategories.append(_subcategory_item(subcategory, *events_counts(subcategory), is_events=True))
            # Проверка на аукцион
            elif subcategory.is_auction:
                visible_subcategories.append(_subcategory_item(subcategory, *auction_counts(), is_auction=True))
            # Проверка на прием заявок (подача) - скрываем для членов гильдии
            elif subcategory.is_reception:
                if is_guild_member:
                    continue
                visible_subcategories.append(_subcategory_item(subcategory, 0, 0, is_reception=True))
            # Проверка на просмотр заявок (только для членов гильдии)
            elif subcategory.is_reception_view:
                if is_guild_member or request.user.is_superuser:
                    visible_subcategories.append(_subcategory_item(subcategory, *reception_counts(), is_reception_view=True))
            else:
                last_post = _last_post(subcategory) if subcategory.topics_num else None
                visible_subcategories.append(_subcategory_item(
                    subcategory, subcategory.topics_num, subcategory.posts_num, last_post=last_post
                ))

        visible_subcategories.sort(key=lambda x: (x.get('order', 0), x['title']))

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

    # Проверка на ивентовую подкатегорию
    if subcategory.is_events:
        return redirect('events:event_index')

    # Проверка на аукцион
    if subcategory.is_auction:
        if not check_auction_access(request.user):
            raise PermissionDenied("У вас нет доступа к аукциону")
        return redirect('auction:auction_index')

    # Проверка на прием заявок (подача)
    if subcategory.is_reception:
        return redirect('reception:application_form')

    # Проверка на просмотр заявок (голосование)
    if subcategory.is_reception_view:
        if not request.user.is_authenticated or not check_guild_member(request.user):
            raise PermissionDenied("Только члены гильдии могут просматривать заявки")
        return redirect('reception:application_list')

    context = {'subcategory': subcategory}
    return render(request, 'forum/subcategory_detail.html', context)


def _save_post_images(post, files):
    for image in files:
        PostImage.objects.create(post=post, image=image)


@login_required
def topic_create(request, slug):
    subcategory = get_object_or_404(SubCategory, slug=slug)

    # Проверяем доступ к подкатегории
    if not subcategory.is_visible_to_user(request.user):
        raise PermissionDenied("У вас нет доступа к этой подкатегории")

    # Проверяем по флагу is_events
    if subcategory.is_events:
        return redirect('events:event_index')

    # Проверяем по флагу is_auction
    if subcategory.is_auction:
        return redirect('auction:auction_index')

    # Проверяем по флагам заявок
    if subcategory.is_reception or subcategory.is_reception_view:
        messages.warning(request, 'В этой подкатегории нельзя создавать темы')
        return redirect('index')

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

            # Создаем пост
            post = Post.objects.create(
                content=form.cleaned_data['content'],
                author=request.user,
                topic=topic
            )

            # Сохраняем все загруженные изображения
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

    # Проверяем доступ к подкатегории темы
    if not topic.subcategory.is_visible_to_user(request.user):
        raise PermissionDenied("У вас нет доступа к этой теме")

    # Если это ивентовая подкатегория - редирект
    if topic.subcategory.is_events:
        return redirect('events:event_index')

    # Если это аукцион - редирект
    if topic.subcategory.is_auction:
        return redirect('auction:auction_index')

    # Если это подкатегория заявок - редирект
    if topic.subcategory.is_reception:
        return redirect('reception:application_form')

    if topic.subcategory.is_reception_view:
        return redirect('reception:application_list')

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

    # Проверяем доступ к подкатегории
    if not topic.subcategory.is_visible_to_user(request.user):
        raise PermissionDenied("У вас нет доступа к этой теме")

    if request.user != topic.author and not request.user.is_superuser:
        raise PermissionDenied("У вас нет прав на редактирование этой темы")

    # Если это ивентовая подкатегория или аукцион - редирект
    if topic.subcategory.is_events or topic.subcategory.is_auction:
        messages.warning(request, 'В этой подкатегории нельзя редактировать темы')
        return redirect('index')

    if request.method == 'POST':
        form = TopicEditForm(request.POST, instance=topic)
        if form.is_valid():
            topic = form.save(commit=False)
            if 'title' in form.changed_data:
                # uuslug транслитерирует кириллицу и сам подбирает уникальный slug
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

    # Проверяем доступ к подкатегории
    if not topic.subcategory.is_visible_to_user(request.user):
        raise PermissionDenied("У вас нет доступа к этой теме")

    if request.user != topic.author and not request.user.is_superuser:
        raise PermissionDenied("У вас нет прав на удаление этой темы")

    # Если это ивентовая подкатегория или аукцион - редирект
    if topic.subcategory.is_events or topic.subcategory.is_auction:
        messages.warning(request, 'В этой подкатегории нельзя удалять темы')
        return redirect('index')

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

    # Если это ивентовая подкатегория или аукцион - редирект
    if topic.subcategory.is_events or topic.subcategory.is_auction:
        messages.warning(request, 'В этой подкатегории нельзя создавать сообщения')
        return redirect('index')

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

            # Сохраняем все загруженные изображения
            _save_post_images(post, images)

            messages.success(request, 'Ваш ответ успешно добавлен!')
            return redirect('topic_detail', slug=topic.slug)
        else:
            # Если форма не валидна, показываем ошибки
            messages.error(request, 'Пожалуйста, исправьте ошибки в форме.')
            posts = topic.posts.select_related('author__profile').prefetch_related('images')
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

    # Проверяем доступ к подкатегории
    if not post.topic.subcategory.is_visible_to_user(request.user):
        raise PermissionDenied("У вас нет доступа к этому сообщению")

    if request.user != post.author and not request.user.is_superuser:
        raise PermissionDenied("У вас нет прав на редактирование этого сообщения")

    # Если это ивентовая подкатегория или аукцион - редирект
    if post.topic.subcategory.is_events or post.topic.subcategory.is_auction:
        messages.warning(request, 'В этой подкатегории нельзя редактировать сообщения')
        return redirect('index')

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

        # Обработка удаления изображений
        for image in images_to_delete:
            image.image.delete(save=False)
            image.delete()

        # Добавление новых изображений
        _save_post_images(post, new_images)

        post.save()
        messages.success(request, 'Сообщение успешно отредактировано')

    return redirect('topic_detail', slug=post.topic.slug)


@login_required
def post_delete(request, post_id):
    post = get_object_or_404(Post, id=post_id)

    # Проверяем доступ к подкатегории
    if not post.topic.subcategory.is_visible_to_user(request.user):
        raise PermissionDenied("У вас нет доступа к этому сообщению")

    if request.user != post.author and not request.user.is_superuser:
        raise PermissionDenied("У вас нет прав на удаление этого сообщения")

    # Если это ивентовая подкатегория или аукцион - редирект
    if post.topic.subcategory.is_events or post.topic.subcategory.is_auction:
        messages.warning(request, 'В этой подкатегории нельзя удалять сообщения')
        return redirect('index')

    if request.method == 'POST':
        topic_slug = post.topic.slug
        post.delete()
        messages.success(request, 'Сообщение успешно удалено')
        return redirect('topic_detail', slug=topic_slug)

    return redirect('topic_detail', slug=post.topic.slug)
