from django.conf import settings
from django.db import models


class TechnicalSEOWebsite(models.Model):
    website_url = models.URLField(max_length=500)
    note = models.TextField(blank=True)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='technical_seo_websites',
    )
    is_active = models.BooleanField(default=True)
    date_added = models.DateTimeField(auto_now_add=True)
    date_modified = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'page_speed_and_cwv_technicalseowebsite'
        ordering = ['-date_added']
        indexes = [
            models.Index(fields=['added_by', '-date_added']),
        ]

    def __str__(self):
        return self.website_url


class TechnicalSEOAudit(models.Model):
    STATUS_RUNNING = 'running'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'

    STATUS_CHOICES = [
        (STATUS_RUNNING, 'Running'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED, 'Failed'),
    ]

    website = models.ForeignKey(
        TechnicalSEOWebsite,
        on_delete=models.CASCADE,
        related_name='technical_seo_audits',
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='technical_seo_audits',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_RUNNING)
    max_pages = models.PositiveSmallIntegerField(default=50)
    pages_crawled = models.PositiveSmallIntegerField(default=0)
    issues_found = models.PositiveSmallIntegerField(default=0)
    critical_issues = models.PositiveSmallIntegerField(default=0)
    high_issues = models.PositiveSmallIntegerField(default=0)
    medium_issues = models.PositiveSmallIntegerField(default=0)
    low_issues = models.PositiveSmallIntegerField(default=0)
    ai_summary = models.TextField(blank=True)
    ai_model = models.CharField(max_length=100, blank=True)
    ai_error = models.TextField(blank=True)
    gsc_status = models.CharField(max_length=100, blank=True)
    gsc_error = models.TextField(blank=True)
    gsc_site_url = models.CharField(max_length=500, blank=True)
    gsc_start_date = models.DateField(null=True, blank=True)
    gsc_end_date = models.DateField(null=True, blank=True)
    gsc_country_filter = models.CharField(max_length=20, blank=True)
    gsc_device_filter = models.CharField(max_length=20, blank=True)
    gsc_rows_found = models.PositiveIntegerField(default=0)
    gsc_inspections_found = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'page_speed_and_cwv_technicalseoaudit'
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['website', '-started_at']),
            models.Index(fields=['requested_by', '-started_at']),
        ]

    def __str__(self):
        return f'{self.website} - Technical SEO - {self.started_at:%Y-%m-%d %H:%M}'


class TechnicalSEOPage(models.Model):
    audit = models.ForeignKey(
        TechnicalSEOAudit,
        on_delete=models.CASCADE,
        related_name='pages',
    )
    url = models.URLField(max_length=1000)
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    final_url = models.URLField(max_length=1000, blank=True)
    content_type = models.CharField(max_length=255, blank=True)
    title = models.CharField(max_length=500, blank=True)
    meta_description = models.TextField(blank=True)
    canonical_url = models.URLField(max_length=1000, blank=True)
    robots_directives = models.CharField(max_length=255, blank=True)
    h1_count = models.PositiveSmallIntegerField(default=0)
    h2_count = models.PositiveSmallIntegerField(default=0)
    internal_links_count = models.PositiveSmallIntegerField(default=0)
    external_links_count = models.PositiveSmallIntegerField(default=0)
    images_count = models.PositiveSmallIntegerField(default=0)
    images_missing_alt_count = models.PositiveSmallIntegerField(default=0)
    depth = models.PositiveSmallIntegerField(default=0)
    load_time_ms = models.PositiveIntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    raw_data = models.JSONField(default=dict, blank=True)
    scanned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'page_speed_and_cwv_technicalseopage'
        ordering = ['depth', 'url']
        indexes = [
            models.Index(fields=['audit', 'status_code']),
            models.Index(fields=['audit', 'depth']),
        ]

    def __str__(self):
        return self.url


class TechnicalSEOIssue(models.Model):
    SEVERITY_CRITICAL = 'critical'
    SEVERITY_HIGH = 'high'
    SEVERITY_MEDIUM = 'medium'
    SEVERITY_LOW = 'low'

    SEVERITY_CHOICES = [
        (SEVERITY_CRITICAL, 'Critical'),
        (SEVERITY_HIGH, 'High'),
        (SEVERITY_MEDIUM, 'Medium'),
        (SEVERITY_LOW, 'Low'),
    ]

    STATUS_OPEN = 'open'
    STATUS_FIXED = 'fixed'
    STATUS_IGNORED = 'ignored'

    STATUS_CHOICES = [
        (STATUS_OPEN, 'Open'),
        (STATUS_FIXED, 'Fixed'),
        (STATUS_IGNORED, 'Ignored'),
    ]

    audit = models.ForeignKey(
        TechnicalSEOAudit,
        on_delete=models.CASCADE,
        related_name='issues',
    )
    page = models.ForeignKey(
        TechnicalSEOPage,
        on_delete=models.CASCADE,
        related_name='issues',
        null=True,
        blank=True,
    )
    issue_type = models.CharField(max_length=100)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES)
    title = models.CharField(max_length=255)
    evidence = models.TextField(blank=True)
    recommendation = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'page_speed_and_cwv_technicalseoissue'
        ordering = ['severity', 'issue_type', 'created_at']
        indexes = [
            models.Index(fields=['audit', 'severity']),
            models.Index(fields=['audit', 'issue_type']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f'{self.title} ({self.severity})'


class TechnicalSEOSearchConsoleRow(models.Model):
    audit = models.ForeignKey(
        TechnicalSEOAudit,
        on_delete=models.CASCADE,
        related_name='gsc_rows',
    )
    page_url = models.URLField(max_length=1000, blank=True)
    query = models.CharField(max_length=500, blank=True)
    device = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=20, blank=True)
    clicks = models.FloatField(default=0)
    impressions = models.FloatField(default=0)
    ctr = models.FloatField(default=0)
    position = models.FloatField(default=0)
    date_range_start = models.DateField(null=True, blank=True)
    date_range_end = models.DateField(null=True, blank=True)
    raw_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-clicks', '-impressions', 'position']
        indexes = [
            models.Index(fields=['audit', '-clicks']),
            models.Index(fields=['audit', 'page_url']),
            models.Index(fields=['audit', 'query']),
        ]

    def __str__(self):
        return f'{self.query or self.page_url} ({self.clicks} clicks)'


class TechnicalSEOURLInspection(models.Model):
    audit = models.ForeignKey(
        TechnicalSEOAudit,
        on_delete=models.CASCADE,
        related_name='gsc_url_inspections',
    )
    page = models.ForeignKey(
        TechnicalSEOPage,
        on_delete=models.CASCADE,
        related_name='gsc_inspections',
        null=True,
        blank=True,
    )
    inspection_url = models.URLField(max_length=1000)
    verdict = models.CharField(max_length=100, blank=True)
    coverage_state = models.CharField(max_length=255, blank=True)
    indexing_state = models.CharField(max_length=100, blank=True)
    robots_txt_state = models.CharField(max_length=100, blank=True)
    page_fetch_state = models.CharField(max_length=100, blank=True)
    google_canonical = models.URLField(max_length=1000, blank=True)
    user_canonical = models.URLField(max_length=1000, blank=True)
    last_crawl_time = models.DateTimeField(null=True, blank=True)
    mobile_usability_verdict = models.CharField(max_length=100, blank=True)
    rich_results_verdict = models.CharField(max_length=100, blank=True)
    error_message = models.TextField(blank=True)
    raw_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['inspection_url']
        indexes = [
            models.Index(fields=['audit', 'verdict']),
            models.Index(fields=['audit', 'inspection_url']),
        ]

    def __str__(self):
        return f'{self.inspection_url} - {self.verdict or "Unknown"}'
