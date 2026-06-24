from django.urls import path

from . import views


app_name = 'serp_analysis'

urlpatterns = [
    path('', views.analysis_view, name='analysis'),
    path('run/', views.run_analysis_view, name='run'),
    path('history/', views.history_view, name='history'),
    path('<int:analysis_id>/', views.detail_view, name='detail'),
    path('<int:analysis_id>/delete/', views.delete_view, name='delete'),
    path('analysis/<int:analysis_id>/status/',views.serp_status_view,name='analysis-status'),
]

