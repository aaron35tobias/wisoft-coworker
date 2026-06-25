from django.urls import path

from . import views


app_name = 'keyword_research'

urlpatterns = [
    path('', views.research_view, name='research'),
    path('run/', views.run_research_view, name='run'),
    path('history/', views.history_view, name='history'),
    path('<int:run_id>/cart/add/', views.add_cart_keyword_view, name='cart-add'),
    path('<int:run_id>/cart/remove/', views.remove_cart_keyword_view, name='cart-remove'),
    path('<int:run_id>/', views.detail_view, name='detail'),
    path('<int:run_id>/delete/', views.delete_run_view, name='delete'),
    path('run/<int:run_id>/status/',views.keyword_run_status_view,name='run-status'),
]
