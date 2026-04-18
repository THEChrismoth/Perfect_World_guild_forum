from django.urls import path
from . import views

app_name = 'reception'

urlpatterns = [
    path('form/', views.application_form, name='application_form'),
    path('success/', views.application_success, name='application_success'),
    path('list/', views.application_list, name='application_list'),
    path('my/', views.my_applications, name='my_applications'),
    path('detail/<int:id>/', views.application_detail, name='application_detail'),
]
