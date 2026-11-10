from django.urls import path
from . import views

app_name = 'auction'

urlpatterns = [
    path('', views.auction_index, name='auction_index'),
    path('lot/<slug:slug>/', views.lot_detail, name='lot_detail'),
    path('lot/<slug:slug>/state/', views.lot_state, name='lot_state'),
    path('my-bids/', views.my_bids, name='my_bids'),
]
