from django.urls import path

from . import views

app_name = 'page_speed_and_cwv'

urlpatterns = [
    path('', views.list_view, name='list'),
    path('websites/list/', views.list_view, name='website-list'),
    path('reports/', views.reports_view, name='reports'),
    path('websites/create/', views.create_view, name='website-create'),
    path('websites/update/', views.update_view, name='website-update'),
    path('websites/<int:website_id>/delete/', views.delete_view, name='website-delete'),
    path('websites/<int:website_id>/reports/', views.reports_view, name='website-reports'),
    path(
        'websites/<int:website_id>/reports/<int:report_index_id>/',
        views.report_detail_view,
        name='website-report-detail',
    ),
]
