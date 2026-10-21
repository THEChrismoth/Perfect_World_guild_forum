from django.urls import path

from . import api

app_name = 'tsbot_api'

urlpatterns = [
    path('state/', api.state, name='state'),
    path('tasks/<int:task_id>/', api.task_result, name='task_result'),
    path('presence/', api.presence, name='presence'),
    path('license/', api.license_file, name='license'),
]
