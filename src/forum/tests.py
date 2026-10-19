from django.contrib.auth.models import User, Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Category, SubCategory, Topic, Post, PostImage


@override_settings(SECURE_SSL_REDIRECT=False)
class ForumTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('alice', password='pass')
        self.category = Category.objects.create(title='Общее', slug='general')
        self.subcategory = SubCategory.objects.create(title='Болталка', slug='chat', category=self.category)
        self.topic = Topic.objects.create(title='Первая тема', author=self.user, subcategory=self.subcategory)
        Post.objects.create(content='Текст', author=self.user, topic=self.topic)
        self.client.force_login(self.user)


class TopicEditTests(ForumTestCase):
    def test_edit_title_with_cyrillic(self):
        response = self.client.post(reverse('topic_edit', args=[self.topic.slug]), {'title': 'Новое название'})

        self.topic.refresh_from_db()
        self.assertEqual(self.topic.title, 'Новое название')
        self.assertTrue(self.topic.slug)
        self.assertRedirects(response, reverse('topic_detail', args=[self.topic.slug]))

    def test_delete_confirmation_page(self):
        response = self.client.get(reverse('topic_delete', args=[self.topic.slug]))
        self.assertEqual(response.status_code, 200)


class PostImageTests(ForumTestCase):
    def test_non_image_upload_rejected(self):
        fake = SimpleUploadedFile('evil.html', b'<script>alert(1)</script>', content_type='image/png')
        self.client.post(reverse('post_create', args=[self.topic.slug]), {'content': 'Ответ', 'images': [fake]})

        self.assertFalse(PostImage.objects.exists())
        self.assertEqual(self.topic.posts.count(), 1)


class VisibilityTests(ForumTestCase):
    def test_group_restricted_subcategory(self):
        group = Group.objects.create(name='Член гильдии')
        self.subcategory.view_groups.add(group)

        self.assertFalse(self.subcategory.is_visible_to_user(self.user))

        # Группы кешируются на объекте пользователя, берем свежий
        self.user.groups.add(group)
        user = User.objects.get(pk=self.user.pk)
        self.assertTrue(self.subcategory.is_visible_to_user(user))

    def test_forum_index_renders(self):
        response = self.client.get(reverse('index'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Болталка')
