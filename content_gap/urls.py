from django.urls import path

from . import views


app_name = 'content_gap'

urlpatterns = [
    path('', views.analysis_form_view, name='analysis'),
    path('run/', views.analysis_run_view, name='analysis-run'),
    path('history/', views.analysis_history_view, name='history'),
    path('<int:analysis_id>/delete/', views.analysis_delete_view, name='analysis-delete'),
    path('<int:analysis_id>/export/excel/', views.analysis_export_excel_view, name='analysis-export-excel'),
    path('<int:analysis_id>/export/pdf/', views.analysis_export_pdf_view, name='analysis-export-pdf'),
    path('<int:analysis_id>/', views.analysis_detail_view, name='analysis-detail'),
    path('analysis/<int:analysis_id>/status/',views.analysis_status_view,name='analysis-status'),
]
