from django.urls import path

from . import views

app_name = 'page_speed_and_cwv'

urlpatterns = [
    path('', views.list_view, name='list'),
    path('websites/list/', views.list_view, name='website-list'),
    path('websites/create/', views.create_view, name='website-create'),
    path('websites/update/', views.update_view, name='website-update'),
    path('websites/<int:website_id>/delete/', views.delete_view, name='website-delete'),
    path('websites/validate/', views.validate_website_view, name='website-validate'),
    path('websites/<int:website_id>/overview/', views.reports_view, name='website-overview'),
    path('overview/', views.reports_view, name='overview'),
    path('websites/<int:website_id>/overview/<int:report_index_id>/', views.report_detail_view, name='website-overview-detail'),

    path('websites/pages/list/', views.list_pages_view, name='page-list'),
    path('websites/pages/validate/', views.validate_page_view, name='page-validate'),
    path('websites/pages/create/', views.create_page_view, name='page-create'),
    path('websites/pages/update/', views.update_page_view, name='page-update'),
    path('websites/pages/<int:page_id>/delete/', views.delete_page_view, name='page-delete'),
]
