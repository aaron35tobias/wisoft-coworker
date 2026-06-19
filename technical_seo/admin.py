from django.contrib import admin

from .models import (
    TechnicalSEOAudit,
    TechnicalSEOIssue,
    TechnicalSEOPage,
    TechnicalSEOSearchConsoleRow,
    TechnicalSEOURLInspection,
    TechnicalSEOWebsite,
)


@admin.register(TechnicalSEOWebsite)
class TechnicalSEOWebsiteAdmin(admin.ModelAdmin):
    list_display = (
        'website_url',
        'added_by',
        'is_active',
        'date_added',
        'date_modified',
    )
    search_fields = ('website_url', 'added_by__username', 'added_by__email')
    list_filter = ('is_active', 'date_added', 'date_modified')


class TechnicalSEOIssueInline(admin.TabularInline):
    model = TechnicalSEOIssue
    extra = 0
    fields = ('severity', 'issue_type', 'title', 'status')
    readonly_fields = ('severity', 'issue_type', 'title', 'status')
    can_delete = False


@admin.register(TechnicalSEOAudit)
class TechnicalSEOAuditAdmin(admin.ModelAdmin):
    list_display = (
        'website',
        'status',
        'pages_crawled',
        'issues_found',
        'critical_issues',
        'high_issues',
        'started_at',
    )
    search_fields = ('website__website_url', 'requested_by__username', 'requested_by__email')
    list_filter = ('status', 'started_at')
    readonly_fields = ('started_at', 'completed_at')


@admin.register(TechnicalSEOPage)
class TechnicalSEOPageAdmin(admin.ModelAdmin):
    list_display = ('url', 'audit', 'status_code', 'depth', 'h1_count', 'images_missing_alt_count')
    search_fields = ('url', 'title', 'audit__website__website_url')
    list_filter = ('status_code', 'depth', 'scanned_at')
    inlines = [TechnicalSEOIssueInline]


@admin.register(TechnicalSEOIssue)
class TechnicalSEOIssueAdmin(admin.ModelAdmin):
    list_display = ('title', 'severity', 'issue_type', 'status', 'audit', 'created_at')
    search_fields = ('title', 'issue_type', 'evidence', 'recommendation', 'page__url')
    list_filter = ('severity', 'status', 'issue_type', 'created_at')


@admin.register(TechnicalSEOSearchConsoleRow)
class TechnicalSEOSearchConsoleRowAdmin(admin.ModelAdmin):
    list_display = ('query', 'page_url', 'device', 'country', 'clicks', 'impressions', 'position', 'audit')
    search_fields = ('query', 'page_url', 'audit__website__website_url')
    list_filter = ('device', 'country', 'date_range_start', 'date_range_end')


@admin.register(TechnicalSEOURLInspection)
class TechnicalSEOURLInspectionAdmin(admin.ModelAdmin):
    list_display = ('inspection_url', 'verdict', 'coverage_state', 'indexing_state', 'audit')
    search_fields = ('inspection_url', 'coverage_state', 'audit__website__website_url')
    list_filter = ('verdict', 'indexing_state', 'robots_txt_state', 'created_at')
