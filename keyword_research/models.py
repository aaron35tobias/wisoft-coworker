from django.conf import settings
from django.db import models


class KeywordResearchProject(models.Model):
    website_url = models.URLField(max_length=500, blank=True)
    seed_keywords = models.TextField(blank=True)
    target_location = models.CharField(max_length=255)
    language = models.CharField(max_length=100, blank=True)
    seed_topic = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='keyword_research_projects',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['added_by', '-created_at']),
        ]

    def __str__(self):
        subject = self.website_url or self.seed_keywords
        return f'{subject} - {self.target_location}'


class KeywordResearchRun(models.Model):
    STATUS_RUNNING = 'running'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'

    STATUS_CHOICES = [
        (STATUS_RUNNING, 'Running'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED, 'Failed'),
    ]

    project = models.ForeignKey(
        KeywordResearchProject,
        on_delete=models.CASCADE,
        related_name='runs',
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='keyword_research_runs',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_RUNNING)
    max_pages = models.PositiveSmallIntegerField(default=20)
    pages_crawled = models.PositiveSmallIntegerField(default=0)
    ai_summary = models.TextField(blank=True)
    ai_model = models.CharField(max_length=100, blank=True)
    ai_error = models.TextField(blank=True)
    planner_status = models.CharField(max_length=100, blank=True)
    planner_error = models.TextField(blank=True)
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

    def __str__(self):
        subject = self.project.website_url or self.project.seed_keywords
        return f'{subject} - Keyword Research - {self.started_at:%Y-%m-%d %H:%M}'


class KeywordResearchPage(models.Model):
    run = models.ForeignKey(
        KeywordResearchRun,
        on_delete=models.CASCADE,
        related_name='pages',
    )
    url = models.URLField(max_length=1000)
    title = models.CharField(max_length=500, blank=True)
    meta_description = models.TextField(blank=True)
    h1 = models.JSONField(default=list, blank=True)
    h2 = models.JSONField(default=list, blank=True)
    h3 = models.JSONField(default=list, blank=True)
    word_count = models.PositiveIntegerField(default=0)
    top_terms = models.JSONField(default=list, blank=True)
    content_excerpt = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    raw_data = models.JSONField(default=dict, blank=True)
    crawled_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['url']
        indexes = [
            models.Index(fields=['run']),
        ]

    def __str__(self):
        return self.url


class KeywordIdea(models.Model):
    PRIORITY_HIGH = 'High'
    PRIORITY_MEDIUM = 'Medium'
    PRIORITY_LOW = 'Low'

    run = models.ForeignKey(
        KeywordResearchRun,
        on_delete=models.CASCADE,
        related_name='keyword_ideas',
    )
    keyword = models.CharField(max_length=255)
    intent = models.CharField(max_length=100, blank=True)
    funnel_stage = models.CharField(max_length=100, blank=True)
    priority = models.CharField(max_length=20, blank=True)
    suggested_page = models.CharField(max_length=500, blank=True)
    content_angle = models.TextField(blank=True)
    reason = models.TextField(blank=True)
    source = models.CharField(max_length=50, default='ai')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['priority', 'keyword']
        indexes = [
            models.Index(fields=['run']),
            models.Index(fields=['keyword']),
        ]

    def __str__(self):
        return self.keyword


class KeywordCluster(models.Model):
    run = models.ForeignKey(
        KeywordResearchRun,
        on_delete=models.CASCADE,
        related_name='clusters',
    )
    cluster_name = models.CharField(max_length=255)
    intent = models.CharField(max_length=100, blank=True)
    keywords = models.JSONField(default=list, blank=True)
    recommended_page_type = models.CharField(max_length=255, blank=True)
    recommended_action = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['cluster_name']
        indexes = [
            models.Index(fields=['run']),
        ]

    def __str__(self):
        return self.cluster_name


class KeywordPlannerMetric(models.Model):
    run = models.ForeignKey(
        KeywordResearchRun,
        on_delete=models.CASCADE,
        related_name='planner_metrics',
    )
    keyword = models.CharField(max_length=255)
    avg_monthly_searches = models.PositiveIntegerField(null=True, blank=True)
    competition = models.CharField(max_length=100, blank=True)
    competition_index = models.PositiveSmallIntegerField(null=True, blank=True)
    low_top_of_page_bid = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    high_top_of_page_bid = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    currency_code = models.CharField(max_length=20, blank=True)
    source = models.CharField(max_length=100, default='google_keyword_planner')
    raw_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['keyword']
        indexes = [
            models.Index(fields=['run']),
            models.Index(fields=['keyword']),
        ]

    def __str__(self):
        return self.keyword


class KeywordCartItem(models.Model):
    SOURCE_AI = 'ai'
    SOURCE_GOOGLE = 'google'

    SOURCE_CHOICES = [
        (SOURCE_AI, 'AI Keyword Ideas'),
        (SOURCE_GOOGLE, 'Google Keyword Planner'),
    ]

    run = models.ForeignKey(
        KeywordResearchRun,
        on_delete=models.CASCADE,
        related_name='cart_items',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='keyword_cart_items',
    )
    keyword = models.CharField(max_length=255)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['keyword']
        constraints = [
            models.UniqueConstraint(fields=['run', 'user', 'keyword'], name='unique_keyword_cart_item'),
        ]
        indexes = [
            models.Index(fields=['run', 'user'], name='keyword_res_run_id_7d4d6b_idx'),
            models.Index(fields=['keyword'], name='keyword_res_keyword_0f783b_idx'),
        ]

    def __str__(self):
        return self.keyword
