from django.conf import settings
from django.db import models


class ContentGapProject(models.Model):
    website_url = models.URLField(max_length=500)
    target_topic = models.CharField(max_length=255, blank=True)
    target_market = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='content_gap_projects',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['added_by', '-created_at']),
        ]

    def __str__(self):
        return self.website_url


class ContentGapAnalysis(models.Model):
    STATUS_RUNNING = 'running'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'

    STATUS_CHOICES = [
        (STATUS_RUNNING, 'Running'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED, 'Failed'),
    ]

    project = models.ForeignKey(
        ContentGapProject,
        on_delete=models.CASCADE,
        related_name='analyses',
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='content_gap_analyses',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_RUNNING)
    own_url = models.URLField(max_length=1000)
    competitor_urls = models.JSONField(default=list, blank=True)
    own_page_snapshot = models.JSONField(default=dict, blank=True)
    competitor_snapshots = models.JSONField(default=list, blank=True)
    content_gaps = models.JSONField(default=list, blank=True)
    keyword_opportunities = models.JSONField(default=list, blank=True)
    recommended_sections = models.JSONField(default=list, blank=True)
    execution_plan = models.JSONField(default=list, blank=True)
    wireframe = models.JSONField(default=dict, blank=True)
    ai_summary = models.TextField(blank=True)
    ai_model = models.CharField(max_length=100, blank=True)
    ai_error = models.TextField(blank=True)
    ai_prompt_chars = models.PositiveIntegerField(default=0)
    ai_input_tokens = models.PositiveIntegerField(default=0)
    ai_output_tokens = models.PositiveIntegerField(default=0)
    ai_total_tokens = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['project', '-started_at']),
            models.Index(fields=['requested_by', '-started_at']),
            models.Index(fields=['status']),
        ]

    @property
    def competitor_count(self):
        return len(self.competitor_urls or [])

    @property
    def display_ai_summary(self):
        summary = (self.ai_summary or '').strip()
        if summary.startswith('{') or summary.startswith('['):
            return (
                'The AI response could not be displayed cleanly, so the structured recommendations below '
                'use the saved fallback analysis from the page and competitor comparison.'
            )
        return summary or 'No AI summary available.'

    @property
    def display_ai_error(self):
        error = (self.ai_error or '').strip()
        if not error:
            return ''
        if error.startswith('Could not parse Claude JSON'):
            return (
                'Claude returned a response that was not formatted cleanly. The platform is showing '
                'the structured fallback recommendations generated from the page comparison.'
            )
        return error

    def __str__(self):
        return f'{self.own_url} - Content Gap - {self.started_at:%Y-%m-%d %H:%M}'
