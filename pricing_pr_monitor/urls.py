from django.urls import path

from . import views


app_name = 'pricing_pr_monitor'

urlpatterns = [
    path('', views.monitors_view, name='monitors'),
    path('run/', views.monitor_run_view, name='monitor-run'),
    path('history/', views.history_view, name='history'),
    path('<int:monitor_id>/', views.monitor_detail_view, name='monitor-detail'),
    path('<int:monitor_id>/run/', views.monitor_run_view, name='monitor-run-existing'),
    path('runs/<int:run_id>/', views.run_detail_view, name='run-detail'),
    path('runs/<int:run_id>/delete/', views.run_delete_view, name='run-delete'),
]
