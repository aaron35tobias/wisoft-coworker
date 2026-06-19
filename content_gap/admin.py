from django.contrib import admin

from .models import ContentGapAnalysis, ContentGapProject


@admin.register(ContentGapProject)
class ContentGapProjectAdmin(admin.ModelAdmin):
    list_display = ('website_url', 'target_topic', 'target_market', 'added_by', 'created_at')
    search_fields = ('website_url', 'target_topic', 'target_market', 'added_by__username', 'added_by__email')
    list_filter = ('created_at',)


@admin.register(ContentGapAnalysis)
class ContentGapAnalysisAdmin(admin.ModelAdmin):
    list_display = ('own_url', 'status', 'requested_by', 'ai_total_tokens', 'started_at', 'completed_at')
    search_fields = ('own_url', 'requested_by__username', 'requested_by__email')
    list_filter = ('status', 'started_at')
    readonly_fields = ('started_at', 'completed_at')
