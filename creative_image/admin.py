from django.contrib import admin
from .models import ImageVariationJob

@admin.register(ImageVariationJob)
class ImageVariationJobAdmin(admin.ModelAdmin):
    list_display = ('id', 'status', 'created_at', 'updated_at')
    list_filter = ('status', 'created_at')
    search_fields = ('id',)
    readonly_fields = ('id', 'created_at', 'updated_at')
