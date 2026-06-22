from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

urlpatterns = [
    path('', include('general.urls')),
    path('accounts/', include('accounts.urls')),
    path('page-speed-and-cwv/', include('page_speed_and_cwv.urls')),
    path('technical-seo-audits/', include('technical_seo.urls')),
    path('content-gaps/', include('content_gap.urls')),
    path('pricing-pr-monitor/', include('pricing_pr_monitor.urls')),
    path('keyword-research/', include('keyword_research.urls')),
    path('serp-analysis/', include('serp_analysis.urls')),
    path('admin/', admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
