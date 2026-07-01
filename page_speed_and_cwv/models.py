from django.conf import settings
from django.db import models

class Website(models.Model):
    website_url = models.URLField(max_length=500)
    note = models.TextField(blank=True)
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name='page_speed_websites')
    is_active = models.BooleanField(default=True)
    date_added = models.DateTimeField(auto_now_add=True)
    date_modified = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date_added']

    def __str__(self):
        return self.website_url

class WebsitePage(models.Model):
    website = models.ForeignKey(Website,on_delete=models.CASCADE,related_name='pages')
    page_url = models.URLField(max_length=500)
    is_active = models.BooleanField(default=True)
    date_added = models.DateTimeField(auto_now_add=True)
    date_modified = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date_added']
        indexes = [
            models.Index(fields=['website', 'page_url']),
        ]

    def __str__(self):
        return self.page_url

class WebsitePageDiscoveryRun(models.Model):
    website = models.ForeignKey(Website,on_delete=models.CASCADE,related_name='page_discovery_runs')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name='page_speed_page_discovery_runs')
    source_summary = models.CharField(max_length=255,blank=True,help_text='Summary of sources used, for example sitemap, robots, homepage.')
    error_message = models.TextField(blank=True)
    date_added = models.DateTimeField(auto_now_add=True)
    date_modified = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date_added']
        indexes = [
            models.Index(fields=['website', '-date_added']),
        ]

    def __str__(self):
        return f'{self.website} - {self.date_added:%Y-%m-%d %H:%M}'

class WebsitePageDiscovery(models.Model):
    discovery_run = models.ForeignKey(WebsitePageDiscoveryRun,on_delete=models.CASCADE,related_name='discovered_pages')
    website = models.ForeignKey(Website,on_delete=models.CASCADE,related_name='page_discoveries')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name='page_speed_page_discoveries')
    page_url = models.URLField(max_length=500)
    source = models.CharField(max_length=50,blank=True,help_text='Discovery source, for example sitemap, robots, or homepage.')
    date_added = models.DateTimeField(auto_now_add=True)
    date_modified = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date_added']
        indexes = [
            models.Index(fields=['website', '-date_added']),
            models.Index(fields=['website', 'page_url']),
        ]

    def __str__(self):
        return self.page_url

class WebsiteSpeedReportAiIndex(models.Model):
    website = models.ForeignKey(Website,on_delete=models.CASCADE,related_name='speed_report_ai_indexes')
    page = models.ForeignKey(WebsitePage,on_delete=models.CASCADE,related_name='speed_report_ai_indexes',null=True,blank=True)
    scan_group_token = models.CharField(max_length=80,blank=True,db_index=True)
    scanned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-scanned_at']
        indexes = [
            models.Index(fields=['website', '-scanned_at']),
            models.Index(fields=['page', '-scanned_at']),
            models.Index(fields=['website', 'scan_group_token']),
        ]

    def __str__(self):
        return f'{self.page or self.website} - {self.scanned_at:%Y-%m-%d %H:%M}'

class WebsiteSpeedReport(models.Model):
    DEVICE_MOBILE = 'mobile'
    DEVICE_DESKTOP = 'desktop'

    DEVICE_TYPE_CHOICES = [
        (DEVICE_MOBILE, 'Mobile'),
        (DEVICE_DESKTOP, 'Desktop'),
    ]

    website = models.ForeignKey(Website,on_delete=models.CASCADE,related_name='speed_reports')
    page = models.ForeignKey(WebsitePage,on_delete=models.CASCADE,related_name='speed_reports',null=True,blank=True)
    report_ai_index = models.ForeignKey(WebsiteSpeedReportAiIndex,on_delete=models.CASCADE,related_name='reports',null=True,blank=True)
    device_type = models.CharField(max_length=20,choices=DEVICE_TYPE_CHOICES)
    performance_score = models.PositiveSmallIntegerField(null=True, blank=True)
    accessibility_score = models.PositiveSmallIntegerField(null=True, blank=True)
    best_practices_score = models.PositiveSmallIntegerField(null=True, blank=True)
    seo_score = models.PositiveSmallIntegerField(null=True, blank=True)
    first_contentful_paint = models.DecimalField(max_digits=8,decimal_places=2,null=True,blank=True,help_text='Seconds')
    largest_contentful_paint = models.DecimalField(max_digits=8,decimal_places=2,null=True,blank=True,help_text='Seconds')
    interaction_to_next_paint = models.DecimalField(max_digits=8,decimal_places=2,null=True,blank=True,help_text='Milliseconds')
    cumulative_layout_shift = models.DecimalField(max_digits=8,decimal_places=4,null=True,blank=True)
    total_blocking_time = models.DecimalField(max_digits=8,decimal_places=2,null=True,blank=True,help_text='Milliseconds')
    speed_index = models.DecimalField(max_digits=8,decimal_places=2,null=True,blank=True,help_text='Seconds')
    time_to_first_byte = models.DecimalField(max_digits=8,decimal_places=2,null=True,blank=True,help_text='Seconds')
    raw_response_json = models.JSONField(blank=True, default=dict)
    scanned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-scanned_at']
        indexes = [
            models.Index(fields=['website', 'device_type', '-scanned_at']),
            models.Index(fields=['page', 'device_type', '-scanned_at']),
        ]

    def __str__(self):
        return f'{self.page or self.website} - {self.device_type} - {self.scanned_at:%Y-%m-%d %H:%M}'

class WebsiteSpeedReportAiEvaluation(models.Model):
    website = models.ForeignKey(Website,on_delete=models.CASCADE,related_name='speed_report_ai_evaluations')
    page = models.ForeignKey(WebsitePage,on_delete=models.CASCADE,related_name='speed_report_ai_evaluations')
    latest_report_index = models.ForeignKey(WebsiteSpeedReportAiIndex,on_delete=models.CASCADE,related_name='latest_ai_evaluations')
    previous_report_index = models.ForeignKey(WebsiteSpeedReportAiIndex,on_delete=models.SET_NULL,related_name='previous_ai_evaluations',null=True,blank=True)
    ai_model = models.CharField(max_length=100,blank=True)
    summary = models.TextField(blank=True)
    improvements_json = models.JSONField(default=list,blank=True)
    declines_json = models.JSONField(default=list,blank=True)
    warnings_json = models.JSONField(default=list,blank=True)
    recommendations_json = models.JSONField(default=list,blank=True)
    raw_ai_response_json = models.JSONField(default=dict,blank=True)
    ai_error = models.TextField(blank=True)
    date_added = models.DateTimeField(auto_now_add=True)
    date_modified = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date_added']
        indexes = [
            models.Index(fields=['website', '-date_added']),
            models.Index(fields=['page', '-date_added']),
            models.Index(fields=['latest_report_index']),
        ]

    def __str__(self):
        return f'{self.page} - {self.latest_report_index} - {self.date_added:%Y-%m-%d %H:%M}'
