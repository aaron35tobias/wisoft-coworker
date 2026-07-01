from django.contrib import admin

from .models import SERPAnalysis


@admin.register(SERPAnalysis)
class SERPAnalysisAdmin(admin.ModelAdmin):
    list_display = ('keyword', 'location', 'status', 'competitor_count', 'requested_by', 'started_at')
    search_fields = ('keyword', 'location', 'target_url')
    list_filter = ('status', 'started_at')
    readonly_fields = ('started_at', 'completed_at')

