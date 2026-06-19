from django.contrib import admin

from .models import (
    PricingPRChange,
    PricingPRMonitor,
    PricingPRNewsMention,
    PricingPRRun,
    PricingPRSnapshot,
)


@admin.register(PricingPRMonitor)
class PricingPRMonitorAdmin(admin.ModelAdmin):
    list_display = ('competitor_name', 'competitor_website', 'is_active', 'added_by', 'created_at')
    search_fields = ('competitor_name', 'competitor_website', 'pricing_url', 'added_by__username', 'added_by__email')
    list_filter = ('is_active', 'created_at')


@admin.register(PricingPRRun)
class PricingPRRunAdmin(admin.ModelAdmin):
    list_display = ('monitor', 'status', 'pages_checked', 'changes_found', 'news_mentions_found', 'started_at')
    search_fields = ('monitor__competitor_name',)
    list_filter = ('status', 'started_at')


@admin.register(PricingPRSnapshot)
class PricingPRSnapshotAdmin(admin.ModelAdmin):
    list_display = ('monitor', 'url', 'status_code', 'checked_at')
    search_fields = ('monitor__competitor_name', 'url', 'title')


@admin.register(PricingPRChange)
class PricingPRChangeAdmin(admin.ModelAdmin):
    list_display = ('monitor', 'change_type', 'severity', 'title', 'created_at')
    search_fields = ('monitor__competitor_name', 'title', 'evidence')
    list_filter = ('severity', 'change_type', 'created_at')


@admin.register(PricingPRNewsMention)
class PricingPRNewsMentionAdmin(admin.ModelAdmin):
    list_display = ('monitor', 'keyword', 'source', 'title', 'published_at')
    search_fields = ('monitor__competitor_name', 'keyword', 'title', 'source')
