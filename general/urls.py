from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard_view, name='home'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('billing/', views.billing_view, name='billing'),
    path('api/chart/token-usage/', views.token_usage_chart_api, name='token_usage_chart_api'),
]
