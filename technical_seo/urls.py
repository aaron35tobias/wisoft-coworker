from django.urls import path

from . import views

app_name = 'technical_seo'

urlpatterns = [
    path('', views.audits_view, name='audits'),
    path('run/', views.audit_run_view, name='audit-run'),
    path('history/', views.audit_history_view, name='history'),
    path('history/websites/<int:website_id>/', views.audit_history_view, name='website-history'),
    path('websites/<int:website_id>/', views.audits_view, name='website-audits'),
    path('<int:audit_id>/delete/', views.audit_delete_view, name='audit-delete'),
    path('<int:audit_id>/export/excel/', views.audit_export_excel_view, name='audit-export-excel'),
    path('<int:audit_id>/export/pdf/', views.audit_export_pdf_view, name='audit-export-pdf'),
    path('<int:audit_id>/', views.audit_detail_view, name='audit-detail'),
    path("audit/<int:audit_id>/status/",views.audit_status_view,name="audit-status"),
]
