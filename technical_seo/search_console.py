import os
from datetime import timedelta, timezone as datetime_timezone
from pathlib import Path

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import TechnicalSEOSearchConsoleRow, TechnicalSEOURLInspection


DEFAULT_GSC_DAYS = 28
DEFAULT_GSC_DATA_LAG_DAYS = 2
DEFAULT_GSC_ROW_LIMIT = 1000
GSC_READONLY_SCOPE = 'https://www.googleapis.com/auth/webmasters.readonly'


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def resolve_path(value, default_name):
    configured = (value or '').strip()
    if configured:
        return Path(configured)
    return Path(settings.BASE_DIR) / default_name


def get_date_range():
    end_date = timezone.localdate() - timedelta(days=env_int('GOOGLE_SEARCH_CONSOLE_DATA_LAG_DAYS', DEFAULT_GSC_DATA_LAG_DAYS))
    start_date = end_date - timedelta(days=env_int('GOOGLE_SEARCH_CONSOLE_DAYS', DEFAULT_GSC_DAYS) - 1)
    return start_date, end_date


def build_site_url(audit):
    return audit.website.website_url


def get_search_console_service():
    service_account_file = resolve_path(
        os.environ.get('GOOGLE_SEARCH_CONSOLE_SERVICE_ACCOUNT_FILE', ''),
        'google-search-console-service-account.json',
    )
    token_file = resolve_path(
        os.environ.get('GOOGLE_SEARCH_CONSOLE_TOKEN_FILE', ''),
        'google-search-console-token.json',
    )

    try:
        from google.oauth2 import service_account
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except Exception:
        return None, 'Search Console dependencies are not installed. Run pip install -r requirements.txt.'

    try:
        credentials = None
        if service_account_file.exists():
            credentials = service_account.Credentials.from_service_account_file(
                str(service_account_file),
                scopes=[GSC_READONLY_SCOPE],
            )
        elif token_file.exists():
            credentials = Credentials.from_authorized_user_file(str(token_file), scopes=[GSC_READONLY_SCOPE])
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
        else:
            return None, (
                'Search Console is not configured. Add a service account JSON file, '
                'or set GOOGLE_SEARCH_CONSOLE_SERVICE_ACCOUNT_FILE / GOOGLE_SEARCH_CONSOLE_TOKEN_FILE.'
            )
        return build('searchconsole', 'v1', credentials=credentials, cache_discovery=False), ''
    except Exception as exc:
        return None, f'Search Console authentication failed: {exc}'


def fetch_search_analytics(audit, service, site_url, start_date, end_date):
    row_limit = env_int('GOOGLE_SEARCH_CONSOLE_ROW_LIMIT', DEFAULT_GSC_ROW_LIMIT)
    body = {
        'startDate': start_date.isoformat(),
        'endDate': end_date.isoformat(),
        'dimensions': ['page', 'query', 'device', 'country'],
        'type': os.environ.get('GOOGLE_SEARCH_CONSOLE_SEARCH_TYPE', 'web').strip() or 'web',
        'rowLimit': max(1, min(row_limit, 25000)),
        'dataState': os.environ.get('GOOGLE_SEARCH_CONSOLE_DATA_STATE', 'final').strip() or 'final',
    }
    filters = []
    if audit.gsc_country_filter:
        filters.append({
            'dimension': 'country',
            'operator': 'equals',
            'expression': audit.gsc_country_filter.upper(),
        })
    if audit.gsc_device_filter:
        filters.append({
            'dimension': 'device',
            'operator': 'equals',
            'expression': audit.gsc_device_filter.upper(),
        })
    if filters:
        body['dimensionFilterGroups'] = [{
            'groupType': 'and',
            'filters': filters,
        }]
    response = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
    rows = response.get('rows', []) or []
    objects = []
    for row in rows:
        keys = row.get('keys', []) or []
        objects.append(TechnicalSEOSearchConsoleRow(
            audit=audit,
            page_url=keys[0] if len(keys) > 0 else '',
            query=(keys[1] if len(keys) > 1 else '')[:500],
            device=(keys[2] if len(keys) > 2 else '')[:100],
            country=(keys[3] if len(keys) > 3 else '')[:20],
            clicks=row.get('clicks') or 0,
            impressions=row.get('impressions') or 0,
            ctr=row.get('ctr') or 0,
            position=row.get('position') or 0,
            date_range_start=start_date,
            date_range_end=end_date,
            raw_data=row,
        ))
    TechnicalSEOSearchConsoleRow.objects.bulk_create(objects, batch_size=500)
    return len(objects)


def parse_gsc_datetime(value):
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, datetime_timezone.utc)
    return parsed


def fetch_url_inspections(audit, service, site_url):
    limit = audit.max_pages
    pages = list(audit.pages.order_by('depth', 'url')[:max(0, limit)])
    count = 0
    for page in pages:
        inspection_url = page.final_url or page.url
        try:
            response = service.urlInspection().index().inspect(body={
                'inspectionUrl': inspection_url,
                'siteUrl': site_url,
            }).execute()
            inspection_result = response.get('inspectionResult', {}) or {}
            index_status = inspection_result.get('indexStatusResult', {}) or {}
            mobile = inspection_result.get('mobileUsabilityResult', {}) or {}
            rich = inspection_result.get('richResultsResult', {}) or {}
            TechnicalSEOURLInspection.objects.create(
                audit=audit,
                page=page,
                inspection_url=inspection_url,
                verdict=index_status.get('verdict', '')[:100],
                coverage_state=index_status.get('coverageState', '')[:255],
                indexing_state=index_status.get('indexingState', '')[:100],
                robots_txt_state=index_status.get('robotsTxtState', '')[:100],
                page_fetch_state=index_status.get('pageFetchState', '')[:100],
                google_canonical=index_status.get('googleCanonical', '')[:1000],
                user_canonical=index_status.get('userCanonical', '')[:1000],
                last_crawl_time=parse_gsc_datetime(index_status.get('lastCrawlTime')),
                mobile_usability_verdict=mobile.get('verdict', '')[:100],
                rich_results_verdict=rich.get('verdict', '')[:100],
                raw_data=response,
            )
        except Exception as exc:
            TechnicalSEOURLInspection.objects.create(
                audit=audit,
                page=page,
                inspection_url=inspection_url,
                error_message=str(exc),
                raw_data={},
            )
        count += 1
    return count


def run_search_console_collection(audit):
    default_start_date, default_end_date = get_date_range()
    start_date = audit.gsc_start_date or default_start_date
    end_date = audit.gsc_end_date or default_end_date
    audit.gsc_status = 'running'
    audit.gsc_error = ''
    audit.gsc_site_url = build_site_url(audit)
    audit.gsc_start_date = start_date
    audit.gsc_end_date = end_date
    audit.save(update_fields=['gsc_status', 'gsc_error', 'gsc_site_url', 'gsc_start_date', 'gsc_end_date'])

    service, error = get_search_console_service()
    if error:
        audit.gsc_status = 'not_configured'
        audit.gsc_error = error
        audit.save(update_fields=['gsc_status', 'gsc_error'])
        return

    TechnicalSEOSearchConsoleRow.objects.filter(audit=audit).delete()
    TechnicalSEOURLInspection.objects.filter(audit=audit).delete()

    try:
        rows_count = fetch_search_analytics(audit, service, audit.gsc_site_url, start_date, end_date)
        inspection_count = fetch_url_inspections(audit, service, audit.gsc_site_url)
    except Exception as exc:
        audit.gsc_status = 'failed'
        audit.gsc_error = str(exc)
        audit.save(update_fields=['gsc_status', 'gsc_error'])
        return

    audit.gsc_status = 'completed'
    audit.gsc_error = ''
    audit.gsc_rows_found = rows_count
    audit.gsc_inspections_found = inspection_count
    audit.save(update_fields=['gsc_status', 'gsc_error', 'gsc_rows_found', 'gsc_inspections_found'])
