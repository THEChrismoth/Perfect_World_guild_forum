from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import Category, Forum, Topic, Post


def index(request):
    categories = Category.objects.prefetch_related('forums').all()
    return render(request, 'forum_app/index.html', {'categories': categories})


def forum_detail(request, forum_id):
    forum = get_object_or_404(Forum, pk=forum_id)
    topics = forum.topics.select_related('author').order_by('-is_pinned', '-created_at')
    return render(request, 'forum_app/forum_detail.html', {'forum': forum, 'topics': topics})


def topic_detail(request, topic_id):
    topic = get_object_or_404(Topic, pk=topic_id)
    posts = topic.posts.select_related('author').all()
    return render(request, 'forum_app/topic_detail.html', {'topic': topic, 'posts': posts})


@login_required
def create_topic(request, forum_id):
    forum = get_object_or_404(Forum, pk=forum_id)
    if request.method == 'POST':
        title = request.POST.get('title')
        content = request.POST.get('content')
        if title and content:
            topic = Topic.objects.create(
                forum=forum,
                author=request.user,
                title=title,
                content=content
            )
            return redirect('topic_detail', topic_id=topic.pk)
    return render(request, 'forum_app/create_topic.html', {'forum': forum})


@login_required
def create_post(request, topic_id):
    topic = get_object_or_404(Topic, pk=topic_id)
    if request.method == 'POST':
        content = request.POST.get('content')
        if content:
            Post.objects.create(
                topic=topic,
                author=request.user,
                content=content
            )
    return redirect('topic_detail', topic_id=topic.pk)
