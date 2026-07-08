from django.urls import path

from . import views

app_name = 'creative_image'

urlpatterns = [
    path('image-variations/', views.image_variations_view, name='image-variations'),
]
