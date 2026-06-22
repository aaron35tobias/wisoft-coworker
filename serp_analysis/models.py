from django.conf import settings
from django.db import models


class SERPAnalysis(models.Model):
    STATUS_RUNNING = 'running'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'

    STATUS_CHOICES = [
        (STATUS_RUNNING, 'Running'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED, 'Failed'),
    ]

    keyword = models.CharField(max_length=255)
    location = models.CharField(max_length=255, blank=True)
    target_url = models.URLField(max_length=1000, blank=True)
    competitor_urls = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_RUNNING)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='serp_analyses',
    )
    target_snapshot = models.JSONField(default=dict, blank=True)
    competitor_snapshots = models.JSONField(default=list, blank=True)
    content_strategies = models.JSONField(default=list, blank=True)
    serp_opportunities = models.JSONField(default=list, blank=True)
    technical_findings = models.JSONField(default=list, blank=True)
    ai_summary = models.TextField(blank=True)
    ai_model = models.CharField(max_length=100, blank=True)
    ai_error = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['requested_by', '-started_at']),
            models.Index(fields=['status']),
            models.Index(fields=['keyword']),
        ]

    @property
    def competitor_count(self):
        return len(self.competitor_urls or [])

    def __str__(self):
        return f'{self.keyword} - SERP Analysis - {self.started_at:%Y-%m-%d %H:%M}'

