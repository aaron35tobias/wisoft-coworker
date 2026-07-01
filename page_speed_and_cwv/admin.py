from django.contrib import admin

from .models import Website, WebsitePage, WebsitePageDiscovery, WebsitePageDiscoveryRun


@admin.register(Website)
class WebsiteAdmin(admin.ModelAdmin):
    list_display = (
        'website_url',
        'added_by',
        'date_added',
        'date_modified',
    )
    search_fields = ('website_url', 'added_by__username', 'added_by__email')
    list_filter = ('date_added', 'date_modified')


@admin.register(WebsitePage)
class WebsitePageAdmin(admin.ModelAdmin):
    list_display = (
        'page_url',
        'website',
        'is_active',
        'date_added',
        'date_modified',
    )
    search_fields = (
        'page_url',
        'website__website_url',
    )
    list_filter = (
        'is_active',
        'date_added',
        'date_modified',
    )


@admin.register(WebsitePageDiscoveryRun)
class WebsitePageDiscoveryRunAdmin(admin.ModelAdmin):
    list_display = (
        'website',
        'created_by',
        'source_summary',
        'date_added',
    )
    search_fields = (
        'website__website_url',
        'created_by__username',
        'created_by__email',
        'source_summary',
        'error_message',
    )
    list_filter = (
        'date_added',
        'date_modified',
    )
    readonly_fields = (
        'date_added',
        'date_modified',
    )


@admin.register(WebsitePageDiscovery)
class WebsitePageDiscoveryAdmin(admin.ModelAdmin):
    list_display = (
        'page_url',
        'website',
        'discovery_run',
        'created_by',
        'source',
        'date_added',
    )
    search_fields = (
        'page_url',
        'website__website_url',
        'created_by__username',
        'created_by__email',
    )
    list_filter = (
        'source',
        'date_added',
        'date_modified',
    )
    readonly_fields = (
        'date_added',
        'date_modified',
    )
