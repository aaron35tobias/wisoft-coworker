from django.urls import path

from . import views

app_name = 'page_speed_and_cwv'

urlpatterns = [
    path('', views.list_view, name='list'),
    path('websites/list/', views.list_view, name='website-list'),
    path('websites/create/', views.create_view, name='website-create'),
    path('websites/update/', views.update_view, name='website-update'),
    path('websites/<int:website_id>/delete/', views.delete_view, name='website-delete'),
]
