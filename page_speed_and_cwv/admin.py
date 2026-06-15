from django.contrib import admin

from .models import Website


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
