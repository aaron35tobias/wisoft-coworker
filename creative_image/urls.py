from django.urls import path

from . import views

app_name = 'creative_image'

urlpatterns = [
    path('image-variations/', views.image_variations_view, name='image-variations'),
    path('api/generate/', views.api_generate, name='api-generate'),
    path('api/status/<uuid:job_id>/', views.api_status, name='api-status'),
]
