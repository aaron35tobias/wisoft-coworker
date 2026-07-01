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

    path('reports/', views.simple_reports_view, name='reports'),
    path('websites/<int:website_id>/reports/', views.simple_reports_view, name='website-reports'),
    path('websites/<int:website_id>/reports/<int:report_index_id>/', views.simple_report_detail_view, name='website-report-detail'),

    path('websites/<int:website_id>/overview/', views.reports_view, name='website-overview'),
    path('websites/<int:website_id>/overview/run-scan/', views.run_website_scan_view, name='website-overview-run-scan'),
    path('websites/<int:website_id>/overview/page/<int:page_id>/', views.page_report_history_view, name='website-overview-page-history'),
    path('websites/<int:website_id>/overview/<int:report_index_id>/modal/', views.report_detail_modal_view, name='website-overview-modal'),

    path('websites/pages/list/', views.list_pages_view, name='page-list'),
    path('websites/pages/create/', views.create_page_view, name='page-create'),
    path('websites/pages/update/', views.update_page_view, name='page-update'),
    path('websites/pages/delete-selected/', views.bulk_delete_pages_view, name='page-bulk-delete'),
    path('websites/pages/<int:page_id>/delete/', views.delete_page_view, name='page-delete'),
    path('websites/pages/validate/', views.validate_page_view, name='page-validate'),
    path('websites/pages/discover/', views.discover_pages_view, name='page-discover'),
    path('websites/pages/discovered/delete-selected/', views.bulk_delete_discovered_pages_view, name='page-discovered-bulk-delete'),
    path('websites/pages/discovered/<int:discovered_page_id>/select/', views.select_discovered_page_view, name='page-discovered-select'),
    path('websites/pages/discovered/select/', views.bulk_select_discovered_pages_view, name='page-discovered-bulk-select'),
]
