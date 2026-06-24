from django.contrib import admin

from .models import Website, WebsitePage


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
