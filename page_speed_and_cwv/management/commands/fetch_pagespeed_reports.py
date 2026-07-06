import json
import os
import re
from decimal import Decimal
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from page_speed_and_cwv.models import (
    Website,
    WebsitePage,
    WebsiteSpeedReport,
    WebsiteSpeedReportAiIndex,
)

PAGESPEED_API_URL = 'https://www.googleapis.com/pagespeedonline/v5/runPagespeed'

class Command(BaseCommand):
    help = 'Fetch PageSpeed Insights reports for active websites.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--website-id',
            type=int,
            help='Fetch reports for one website pages only.',
        )
        parser.add_argument(
            '--page-id',
            type=int,
            help='Fetch reports for one saved page only.',
        )
        parser.add_argument(
            '--strategy',
            choices=[
                WebsiteSpeedReport.DEVICE_MOBILE,
                WebsiteSpeedReport.DEVICE_DESKTOP,
                'both',
            ],
            default='both',
            help='PageSpeed strategy to fetch.',
        )

    def handle(self, *args, **options):
        api_key = os.environ.get('GOOGLE_PAGESPEED_API_KEY')
        if not api_key:
            raise CommandError('GOOGLE_PAGESPEED_API_KEY is not set.')

        pages = WebsitePage.objects.filter(is_active=True, website__is_active=True).select_related('website')

        if options['website_id']:
            pages = pages.filter(website_id=options['website_id'])

        if options['page_id']:
            pages = pages.filter(id=options['page_id'])

        strategies = [options['strategy']]
        if options['strategy'] == 'both':
            strategies = [
                WebsiteSpeedReport.DEVICE_MOBILE,
                WebsiteSpeedReport.DEVICE_DESKTOP,
            ]

        total_reports = 0
        scan_group_tokens = {}
        for page in pages.order_by('website_id', 'id'):
            scan_group_token = scan_group_tokens.setdefault(page.website_id, self.create_scan_group_token(page.website))
            report_ai_index = WebsiteSpeedReportAiIndex.objects.create(website=page.website,page=page,scan_group_token=scan_group_token)
            for strategy in strategies:
                self.stdout.write(f'Fetching {strategy} report for {page.page_url}')
                data = self.fetch_pagespeed_data(
                    url=page.page_url,
                    strategy=strategy,
                    api_key=api_key,
                )
                WebsiteSpeedReport.objects.create(
                    website=page.website,
                    page=page,
                    report_ai_index=report_ai_index,
                    device_type=strategy,
                    performance_score=self.get_category_score(data, 'performance'),
                    accessibility_score=self.get_category_score(data, 'accessibility'),
                    best_practices_score=self.get_category_score(data, 'best-practices'),
                    seo_score=self.get_category_score(data, 'seo'),
                    first_contentful_paint=self.get_audit_seconds(data, 'first-contentful-paint'),
                    largest_contentful_paint=self.get_audit_seconds(data, 'largest-contentful-paint'),
                    interaction_to_next_paint=self.get_audit_milliseconds(data, 'interaction-to-next-paint'),
                    cumulative_layout_shift=self.get_audit_decimal(data, 'cumulative-layout-shift', places='0.0001'),
                    total_blocking_time=self.get_audit_milliseconds(data, 'total-blocking-time'),
                    speed_index=self.get_audit_seconds(data, 'speed-index'),
                    time_to_first_byte=self.get_audit_seconds(data, 'server-response-time'),
                    raw_response_json=data,
                )
                total_reports += 1

        self.stdout.write(self.style.SUCCESS(f'Created {total_reports} PageSpeed report(s).'))

    def create_scan_group_token(self, website):
        parsed_url = urlparse(website.website_url)
        site_name = parsed_url.netloc or parsed_url.path
        site_name = site_name.lower().replace('www.', '').split('.')[0]
        site_prefix = re.sub(r'[^a-z0-9]', '', site_name)[:4].upper() or 'SITE'
        timestamp = timezone.now().strftime('%Y%m%d%H%M%S%f')
        return f'{site_prefix}-{timestamp}'

    def fetch_pagespeed_data(self, url, strategy, api_key):
        params = urlencode({
            'url': url,
            'strategy': strategy,
            'key': api_key,
            'category': ['performance', 'accessibility', 'best-practices', 'seo'],
        }, doseq=True)
        request_url = f'{PAGESPEED_API_URL}?{params}'

        with urlopen(request_url, timeout=120) as response:
            return json.loads(response.read().decode('utf-8'))

    def get_category_score(self, data, category_key):
        score = (
            data.get('lighthouseResult', {})
            .get('categories', {})
            .get(category_key, {})
            .get('score')
        )
        if score is None:
            return None
        return round(score * 100)

    def get_audit_numeric_value(self, data, audit_key):
        value = (
            data.get('lighthouseResult', {})
            .get('audits', {})
            .get(audit_key, {})
            .get('numericValue')
        )
        if value is None:
            return None
        return Decimal(str(value))

    def get_audit_decimal(self, data, audit_key, places='0.01'):
        value = self.get_audit_numeric_value(data, audit_key)
        if value is None:
            return None
        return value.quantize(Decimal(places))

    def get_audit_seconds(self, data, audit_key):
        value = self.get_audit_numeric_value(data, audit_key)
        if value is None:
            return None
        return (value / Decimal('1000')).quantize(Decimal('0.01'))

    def get_audit_milliseconds(self, data, audit_key):
        value = self.get_audit_numeric_value(data, audit_key)
        if value is None:
            return None
        return value.quantize(Decimal('0.01'))
