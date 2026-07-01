from django.urls import path

from . import views


app_name = 'bulk_alt_text'

urlpatterns = [
    path('', views.generate_view, name='generate'),
    path('run/', views.run_view, name='run'),
    path('history/', views.history_view, name='history'),
    path('<int:analysis_id>/delete/', views.delete_view, name='delete'),
    path('<int:analysis_id>/', views.detail_view, name='detail'),
]
