from django.contrib import admin

from .models import BulkAltTextAnalysis


@admin.register(BulkAltTextAnalysis)
class BulkAltTextAnalysisAdmin(admin.ModelAdmin):
    list_display = ('page_url', 'status', 'total_images', 'missing_alt_count', 'generated_alt_count', 'requested_by', 'started_at')
    list_filter = ('status', 'started_at')
    search_fields = ('page_url', 'page_title')
