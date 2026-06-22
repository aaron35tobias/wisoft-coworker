from django.urls import path

from . import views


app_name = 'content_gap'

urlpatterns = [
    path('', views.analysis_form_view, name='analysis'),
    path('run/', views.analysis_run_view, name='analysis-run'),
    path('history/', views.analysis_history_view, name='history'),
    path('<int:analysis_id>/delete/', views.analysis_delete_view, name='analysis-delete'),
    path('<int:analysis_id>/', views.analysis_detail_view, name='analysis-detail'),
]
