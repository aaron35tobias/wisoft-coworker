from django.conf import settings
from django.db import models


class BulkAltTextAnalysis(models.Model):
    STATUS_RUNNING = 'running'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'

    STATUS_CHOICES = [
        (STATUS_RUNNING, 'Running'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED, 'Failed'),
    ]

    page_url = models.URLField(max_length=1000)
    page_title = models.CharField(max_length=500,blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name='bulk_alt_text_analyses')
    status = models.CharField(max_length=20,choices=STATUS_CHOICES,default=STATUS_RUNNING)
    total_images = models.PositiveIntegerField(default=0)
    missing_alt_count = models.PositiveIntegerField(default=0)
    generated_alt_count = models.PositiveIntegerField(default=0)
    images_json = models.JSONField(default=list,blank=True)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True,blank=True)

    class Meta:
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['requested_by', '-started_at']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f'{self.page_url} - Bulk Alt Text - {self.started_at:%Y-%m-%d %H:%M}'
