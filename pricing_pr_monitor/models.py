from django.conf import settings
from django.db import models


class PricingPRMonitor(models.Model):
    competitor_name = models.CharField(max_length=255)
    competitor_website = models.URLField(max_length=500)
    pricing_url = models.URLField(max_length=1000, blank=True)
    monitored_urls = models.JSONField(default=list, blank=True)
    news_keywords = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='pricing_pr_monitors',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['added_by', '-created_at']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return self.competitor_name


class PricingPRRun(models.Model):
    STATUS_RUNNING = 'running'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'

    STATUS_CHOICES = [
        (STATUS_RUNNING, 'Running'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED, 'Failed'),
    ]

    monitor = models.ForeignKey(
        PricingPRMonitor,
        on_delete=models.CASCADE,
        related_name='runs',
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='pricing_pr_runs',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_RUNNING)
    pages_checked = models.PositiveSmallIntegerField(default=0)
    changes_found = models.PositiveSmallIntegerField(default=0)
    news_mentions_found = models.PositiveSmallIntegerField(default=0)
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
            models.Index(fields=['monitor', '-started_at']),
            models.Index(fields=['requested_by', '-started_at']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f'{self.monitor} - {self.started_at:%Y-%m-%d %H:%M}'


class PricingPRSnapshot(models.Model):
    run = models.ForeignKey(
        PricingPRRun,
        on_delete=models.CASCADE,
        related_name='snapshots',
    )
    monitor = models.ForeignKey(
        PricingPRMonitor,
        on_delete=models.CASCADE,
        related_name='snapshots',
    )
    url = models.URLField(max_length=1000)
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    final_url = models.URLField(max_length=1000, blank=True)
    title = models.CharField(max_length=500, blank=True)
    meta_description = models.TextField(blank=True)
    headings = models.JSONField(default=list, blank=True)
    pricing_terms = models.JSONField(default=list, blank=True)
    cta_terms = models.JSONField(default=list, blank=True)
    text_excerpt = models.TextField(blank=True)
    content_hash = models.CharField(max_length=64, blank=True)
    error_message = models.TextField(blank=True)
    raw_data = models.JSONField(default=dict, blank=True)
    checked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['url']
        indexes = [
            models.Index(fields=['monitor', 'url', '-checked_at']),
            models.Index(fields=['run']),
            models.Index(fields=['content_hash']),
        ]

    def __str__(self):
        return self.url


class PricingPRChange(models.Model):
    SEVERITY_HIGH = 'high'
    SEVERITY_MEDIUM = 'medium'
    SEVERITY_LOW = 'low'

    SEVERITY_CHOICES = [
        (SEVERITY_HIGH, 'High'),
        (SEVERITY_MEDIUM, 'Medium'),
        (SEVERITY_LOW, 'Low'),
    ]

    run = models.ForeignKey(
        PricingPRRun,
        on_delete=models.CASCADE,
        related_name='changes',
    )
    monitor = models.ForeignKey(
        PricingPRMonitor,
        on_delete=models.CASCADE,
        related_name='changes',
    )
    previous_snapshot = models.ForeignKey(
        PricingPRSnapshot,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='next_changes',
    )
    current_snapshot = models.ForeignKey(
        PricingPRSnapshot,
        on_delete=models.CASCADE,
        related_name='changes',
    )
    change_type = models.CharField(max_length=100)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default=SEVERITY_LOW)
    title = models.CharField(max_length=255)
    evidence = models.TextField(blank=True)
    recommendation = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['severity', 'created_at']
        indexes = [
            models.Index(fields=['run', 'severity']),
            models.Index(fields=['monitor', '-created_at']),
        ]

    def __str__(self):
        return self.title


class PricingPRNewsMention(models.Model):
    run = models.ForeignKey(
        PricingPRRun,
        on_delete=models.CASCADE,
        related_name='news_mentions',
    )
    monitor = models.ForeignKey(
        PricingPRMonitor,
        on_delete=models.CASCADE,
        related_name='news_mentions',
    )
    keyword = models.CharField(max_length=255)
    title = models.CharField(max_length=500)
    source = models.CharField(max_length=255, blank=True)
    url = models.URLField(max_length=1000)
    published_at = models.DateTimeField(null=True, blank=True)
    snippet = models.TextField(blank=True)
    mention_type = models.CharField(max_length=100, blank=True)
    relevance_reason = models.TextField(blank=True)
    competitive_impact = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-published_at', '-created_at']
        indexes = [
            models.Index(fields=['run']),
            models.Index(fields=['monitor', '-published_at']),
            models.Index(fields=['keyword']),
        ]

    def __str__(self):
        return self.title
