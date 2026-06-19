import json
import os
from decimal import Decimal
from urllib.parse import urlencode
from urllib.request import urlopen
from django.core.management.base import BaseCommand, CommandError
from page_speed_and_cwv.models import (
    Website,
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
            help='Fetch reports for one website only.',
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

        websites = Website.objects.filter(is_active=True)
        if options['website_id']:
            websites = websites.filter(id=options['website_id'])

        strategies = [options['strategy']]
        if options['strategy'] == 'both':
            strategies = [
                WebsiteSpeedReport.DEVICE_MOBILE,
                WebsiteSpeedReport.DEVICE_DESKTOP,
            ]

        total_reports = 0
        for website in websites:
            report_ai_index = WebsiteSpeedReportAiIndex.objects.create(
                website=website,
            )
            for strategy in strategies:
                self.stdout.write(f'Fetching {strategy} report for {website.website_url}')
                data = self.fetch_pagespeed_data(
                    url=website.website_url,
                    strategy=strategy,
                    api_key=api_key,
                )
                WebsiteSpeedReport.objects.create(
                    website=website,
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
