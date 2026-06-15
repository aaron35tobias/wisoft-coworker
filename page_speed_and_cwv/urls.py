from django.urls import path

from . import views

app_name = 'page_speed_and_cwv'

urlpatterns = [
    path('', views.list_view, name='list'),
    path('websites/list/', views.list_view, name='website-list'),
]
