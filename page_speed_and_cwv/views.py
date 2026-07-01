from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.validators import URLValidator
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.shortcuts import get_object_or_404, redirect, render
from urllib.parse import urljoin, urlparse, urldefrag
from urllib.request import Request, urlopen
import re
import xml.etree.ElementTree as ET

from .models import (
    Website,
    WebsitePage,
    WebsitePageDiscovery,
    WebsitePageDiscoveryRun,
    WebsiteSpeedReport,
    WebsiteSpeedReportAiEvaluation,
    WebsiteSpeedReportAiIndex,
)

DISCOVERY_REQUEST_TIMEOUT = 15

def format_report_datetime(value):
    if not value:
        return '-'
    return timezone.localtime(value).strftime('%d %b %Y, %I:%M %p').lstrip('0')

def get_report_issues(report):
    if not report or not report.raw_response_json:
        return []

    audits = report.raw_response_json.get('lighthouseResult', {}).get('audits', {})
    issues = []

    for audit_key, audit in audits.items():
        score = audit.get('score')
        display_mode = audit.get('scoreDisplayMode')

        if display_mode in ['notApplicable', 'manual', 'informative']:
            continue

        if score is not None and score >= 0.9:
            continue

        if score is None and not audit.get('displayValue'):
            continue

        issues.append({
            'audit_key': audit_key,
            'title': audit.get('title', ''),
            'description': audit.get('description', ''),
            'display_value': audit.get('displayValue', ''),
            'score': score,
        })

    return issues[:30]

def get_report_payload(report):
    if not report:
        return None

    lighthouse_result = report.raw_response_json.get('lighthouseResult', {}) if report.raw_response_json else {}

    return {
        'performance_score': report.performance_score,
        'accessibility_score': report.accessibility_score,
        'best_practices_score': report.best_practices_score,
        'seo_score': report.seo_score,
        'first_contentful_paint': str(report.first_contentful_paint) if report.first_contentful_paint is not None else '-',
        'largest_contentful_paint': str(report.largest_contentful_paint) if report.largest_contentful_paint is not None else '-',
        'interaction_to_next_paint': str(report.interaction_to_next_paint) if report.interaction_to_next_paint is not None else '-',
        'cumulative_layout_shift': str(report.cumulative_layout_shift) if report.cumulative_layout_shift is not None else '-',
        'total_blocking_time': str(report.total_blocking_time) if report.total_blocking_time is not None else '-',
        'speed_index': str(report.speed_index) if report.speed_index is not None else '-',
        'time_to_first_byte': str(report.time_to_first_byte) if report.time_to_first_byte is not None else '-',
        'run_warnings': lighthouse_result.get('runWarnings', []),
        'issues': get_report_issues(report),
    }

@login_required(login_url='sign-in')
def list_view(request):
    websites = Website.objects.filter(added_by=request.user).prefetch_related('speed_report_ai_indexes')
    for website in websites:
        scan_indexes = list(website.speed_report_ai_indexes.all())
        website.latest_report = scan_indexes[0] if scan_indexes else None

    context = { 'websites': websites, }
    return render(request, 'page_speed_and_cwv/list.html', context)

@login_required(login_url='sign-in')
def validate_website_view(request):
    website_url = request.GET.get('website_url', '').strip().lower()
    website_id = request.GET.get('website_id')

    if not website_url:
        return JsonResponse(False, safe=False)

    query = Website.objects.filter(added_by=request.user, website_url__iexact=website_url)

    if website_id:
        query = query.exclude(id=website_id)

    if query.exists():
        return JsonResponse('This website has already been added.', safe=False)

    return JsonResponse(True, safe=False)

def page_list_redirect(website_id):
    return f"{reverse('page_speed_and_cwv:page-list')}?website_id={website_id}"

@login_required(login_url='sign-in')
def create_view(request):
    if request.method == 'POST':
        website_url = request.POST.get('website_url', '').strip().lower()
        note = request.POST.get('note', '').strip()
        is_active = request.POST.get('is_active') == '1'

        if not website_url:
            messages.error(request, 'Website URL is required.')
            return redirect('page_speed_and_cwv:website-list')

        try:
            URLValidator()(website_url)
        except ValidationError:
            messages.error(request, 'Enter a valid website URL.')
            return redirect('page_speed_and_cwv:website-list')

        if Website.objects.filter(added_by=request.user, website_url__iexact=website_url).exists():
            messages.error(request, 'This website has already been added.')
            return redirect('page_speed_and_cwv:website-list')

        Website.objects.create(website_url=website_url, note=note, is_active=is_active, added_by=request.user)

        messages.success(request, 'Record inserted successfully.')
        return redirect('page_speed_and_cwv:website-list')

    return redirect('page_speed_and_cwv:website-list')

@login_required(login_url='sign-in')
def update_view(request):
    if request.method == 'POST':
        website_id = request.POST.get('website_id')
        website_url = request.POST.get('website_url', '').strip().lower()
        note = request.POST.get('note', '').strip()
        is_active = request.POST.get('is_active') == '1'
        website = get_object_or_404(Website, id=website_id, added_by=request.user)

        if not website_url:
            messages.error(request, 'Website URL is required.')
            return redirect('page_speed_and_cwv:website-list')

        try:
            URLValidator()(website_url)
        except ValidationError:
            messages.error(request, 'Enter a valid website URL.')
            return redirect('page_speed_and_cwv:website-list')

        if Website.objects.filter(added_by=request.user, website_url__iexact=website_url).exclude(id=website.id).exists():
            messages.error(request, 'This website has already been added.')
            return redirect('page_speed_and_cwv:website-list')

        website.website_url = website_url
        website.note = note
        website.is_active = is_active
        website.save()

        messages.success(request, 'Record updated successfully.')
        return redirect('page_speed_and_cwv:website-list')

    return redirect('page_speed_and_cwv:website-list')

@login_required(login_url='sign-in')
def delete_view(request, website_id):
    website = get_object_or_404(Website, id=website_id, added_by=request.user)

    if request.method == 'POST':
        website.delete()
        messages.success(request, 'Record deleted successfully.')
        return redirect('page_speed_and_cwv:website-list')

    return redirect('page_speed_and_cwv:website-list')

@login_required(login_url='sign-in')
def reports_view(request, website_id=None):
    website = None
    pages = WebsitePage.objects.filter(website__added_by=request.user).select_related('website')

    if website_id is not None:
        website = get_object_or_404(Website, id=website_id, added_by=request.user)
        pages = pages.filter(website=website)

    page_summaries = []
    for page in pages:
        latest_report_index = WebsiteSpeedReportAiIndex.objects.filter(page=page).prefetch_related('reports').first()
        page.latest_report_index = latest_report_index
        page.latest_mobile_report = None
        page.latest_desktop_report = None

        if latest_report_index:
            reports = list(latest_report_index.reports.all())
            page.latest_mobile_report = next(
                (report for report in reports if report.device_type == WebsiteSpeedReport.DEVICE_MOBILE),
                None,
            )
            page.latest_desktop_report = next(
                (report for report in reports if report.device_type == WebsiteSpeedReport.DEVICE_DESKTOP),
                None,
            )

        page.total_scan_runs = WebsiteSpeedReportAiIndex.objects.filter(page=page).count()
        page_summaries.append(page)

    context = {
        'website': website,
        'page_summaries': page_summaries,
        'back_to_websites_url': reverse('page_speed_and_cwv:website-list') if website else '',
    }
    return render(request, 'page_speed_and_cwv/overview.html', context)

@login_required(login_url='sign-in')
def run_website_scan_view(request, website_id):
    website = get_object_or_404(Website, id=website_id, added_by=request.user)

    if request.method != 'POST':
        return redirect('page_speed_and_cwv:website-overview', website_id=website.id)

    try:
        call_command('fetch_pagespeed_reports', website_id=website.id, strategy='both')
        messages.success(request, 'PageSpeed scan completed successfully.')
    except CommandError as error:
        messages.error(request, str(error))
    except Exception as error:
        messages.error(request, f'PageSpeed scan failed: {error}')

    return redirect('page_speed_and_cwv:website-overview', website_id=website.id)

@login_required(login_url='sign-in')
def page_report_history_view(request, website_id, page_id):
    website = get_object_or_404(Website, id=website_id, added_by=request.user)
    page = get_object_or_404(WebsitePage, id=page_id, website=website)
    report_indexes = WebsiteSpeedReportAiIndex.objects.filter(website=website, page=page).select_related('website', 'page').prefetch_related('reports')
    latest_ai_evaluation = WebsiteSpeedReportAiEvaluation.objects.filter(website=website, page=page).select_related('latest_report_index', 'previous_report_index').first()

    for report_index in report_indexes:
        reports = list(report_index.reports.all())
        report_index.mobile_report = next(
            (report for report in reports if report.device_type == WebsiteSpeedReport.DEVICE_MOBILE),
            None,
        )
        report_index.desktop_report = next(
            (report for report in reports if report.device_type == WebsiteSpeedReport.DEVICE_DESKTOP),
            None,
        )

    context = {
        'website': website,
        'page': page,
        'report_indexes': report_indexes,
        'latest_ai_evaluation': latest_ai_evaluation,
        'back_to_overview_url': reverse('page_speed_and_cwv:website-overview', args=[website.id]),
    }
    return render(request, 'page_speed_and_cwv/overview_page_history.html', context)

@login_required(login_url='sign-in')
def report_detail_modal_view(request, website_id, report_index_id):
    website = get_object_or_404(Website, id=website_id, added_by=request.user)
    report_index = get_object_or_404(WebsiteSpeedReportAiIndex.objects.select_related('website', 'page').prefetch_related('reports'), id=report_index_id, website=website)
    reports = list(report_index.reports.all())
    mobile_report = next((report for report in reports if report.device_type == WebsiteSpeedReport.DEVICE_MOBILE), None)
    desktop_report = next((report for report in reports if report.device_type == WebsiteSpeedReport.DEVICE_DESKTOP), None)

    return JsonResponse({
        'scan_id': report_index.scan_group_token or '-',
        'scanned_at': format_report_datetime(report_index.scanned_at),
        'website_url': website.website_url,
        'page_url': report_index.page.page_url if report_index.page else website.website_url,
        'mobile': get_report_payload(mobile_report),
        'desktop': get_report_payload(desktop_report),
    })

@login_required(login_url='sign-in')
def list_pages_view(request):
    website = None
    website_id = request.GET.get('website_id')

    if website_id:
        website = get_object_or_404(Website, id=website_id, added_by=request.user)

    pages = website.pages.all() if website else []
    discovered_pages = list(website.page_discoveries.all().order_by('id')) if website else []
    saved_page_urls = {page.page_url.lower().rstrip('/') for page in pages}

    for discovered_page in discovered_pages:
        discovered_page.is_saved = discovered_page.page_url.lower().rstrip('/') in saved_page_urls

    context = {
        'website': website,
        'pages': pages,
        'discovered_pages': discovered_pages,
        'back_to_websites_url': reverse('page_speed_and_cwv:website-list'),
    }
    return render(request, 'page_speed_and_cwv/list_pages.html', context)

@login_required(login_url='sign-in')
def validate_page_view(request):
    page_url = request.GET.get('page_url', '').strip().lower()
    page_id = request.GET.get('page_id')
    website_id = request.GET.get('website_id')

    if not page_url or not website_id:
        return JsonResponse(False, safe=False)

    query = WebsitePage.objects.filter(website_id=website_id, website__added_by=request.user, page_url__iexact=page_url)

    if page_id:
        query = query.exclude(id=page_id)

    if query.exists():
        return JsonResponse('This page has already been added.', safe=False)

    return JsonResponse(True, safe=False)

@login_required(login_url='sign-in')
def create_page_view(request):
    if request.method != 'POST':
        return redirect('page_speed_and_cwv:website-list')

    website_id = request.POST.get('website_id')
    page_url = request.POST.get('page_url', '').strip().lower()
    is_active = request.POST.get('is_active') == '1'

    website = get_object_or_404(Website, id=website_id, added_by=request.user)

    if not page_url:
        messages.error(request, 'Page URL is required.')
        return redirect(page_list_redirect(website.id))

    try:
        URLValidator()(page_url)
    except ValidationError:
        messages.error(request, 'Enter a valid page URL.')
        return redirect(page_list_redirect(website.id))

    if WebsitePage.objects.filter(website=website, page_url__iexact=page_url).exists():
        messages.error(request, 'This page has already been added.')
        return redirect(page_list_redirect(website.id))

    WebsitePage.objects.create(website=website, page_url=page_url, is_active=is_active)
    messages.success(request, 'Record inserted successfully.')
    return redirect(page_list_redirect(website.id))

@login_required(login_url='sign-in')
def update_page_view(request):
    if request.method != 'POST':
        return redirect('page_speed_and_cwv:website-list')

    page_id = request.POST.get('page_id')
    page_url = request.POST.get('page_url', '').strip().lower()
    is_active = request.POST.get('is_active') == '1'

    page = get_object_or_404(WebsitePage.objects.select_related('website'), id=page_id, website__added_by=request.user)

    if not page_url:
        messages.error(request, 'Page URL is required.')
        return redirect(page_list_redirect(page.website.id))

    try:
        URLValidator()(page_url)
    except ValidationError:
        messages.error(request, 'Enter a valid page URL.')
        return redirect(page_list_redirect(page.website.id))

    if WebsitePage.objects.filter(website=page.website, page_url__iexact=page_url).exclude(id=page.id).exists():
        messages.error(request, 'This page has already been added.')
        return redirect(page_list_redirect(page.website.id))

    page.page_url = page_url
    page.is_active = is_active
    page.save()
    messages.success(request, 'Record updated successfully.')
    return redirect(page_list_redirect(page.website.id))

@login_required(login_url='sign-in')
def delete_page_view(request, page_id):
    page = get_object_or_404(WebsitePage.objects.select_related('website'), id=page_id, website__added_by=request.user)

    if request.method == 'POST':
        website_id = page.website.id
        page.delete()
        messages.success(request, 'Record deleted successfully.')
        return redirect(page_list_redirect(website_id))

    return redirect(page_list_redirect(page.website.id))

@login_required(login_url='sign-in')
def bulk_delete_pages_view(request):
    if request.method != 'POST':
        return redirect('page_speed_and_cwv:website-list')

    page_ids = request.POST.getlist('page_ids[]') or request.POST.getlist('page_ids')
    pages = WebsitePage.objects.filter(id__in=page_ids, website__added_by=request.user)
    deleted_pages = list(pages.values('id', 'page_url'))
    pages.delete()

    return JsonResponse({
        'success': True,
        'deleted_page_ids': [page['id'] for page in deleted_pages],
        'deleted_page_urls': [page['page_url'] for page in deleted_pages],
    })

@login_required(login_url='sign-in')
def select_discovered_page_view(request, discovered_page_id):
    discovered_page = get_object_or_404(WebsitePageDiscovery.objects.select_related('website'), id=discovered_page_id, created_by=request.user, website__added_by=request.user)

    if request.method != 'POST':
        return redirect(page_list_redirect(discovered_page.website.id))

    existing_page = WebsitePage.objects.filter(website=discovered_page.website, page_url__iexact=discovered_page.page_url).first()

    if existing_page:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'already_saved': True, 'message': 'This page is already saved.'})
        messages.error(request, 'This page has already been added.')
        return redirect(page_list_redirect(existing_page.website.id))

    page = WebsitePage.objects.create(website=discovered_page.website, page_url=discovered_page.page_url, is_active=True)

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'already_saved': False,
            'message': 'Page saved successfully.',
            'page': {
                'id': page.id,
                'page_url': page.page_url,
                'is_active': page.is_active,
                'delete_url': reverse('page_speed_and_cwv:page-delete', args=[page.id]),
            },
        })

    messages.success(request, 'Record inserted successfully.')
    return redirect(page_list_redirect(page.website.id))

@login_required(login_url='sign-in')
def bulk_select_discovered_pages_view(request):
    if request.method != 'POST':
        return redirect('page_speed_and_cwv:website-list')

    discovered_page_ids = request.POST.getlist('discovered_page_ids[]') or request.POST.getlist('discovered_page_ids')
    discovered_pages = WebsitePageDiscovery.objects.select_related('website').filter(id__in=discovered_page_ids, created_by=request.user, website__added_by=request.user)

    created_pages = []
    saved_discovered_ids = []

    for discovered_page in discovered_pages:
        if WebsitePage.objects.filter(website=discovered_page.website, page_url__iexact=discovered_page.page_url).exists():
            saved_discovered_ids.append(discovered_page.id)
            continue

        page = WebsitePage.objects.create(website=discovered_page.website, page_url=discovered_page.page_url, is_active=True)
        saved_discovered_ids.append(discovered_page.id)
        created_pages.append({
            'id': page.id,
            'page_url': page.page_url,
            'is_active': page.is_active,
            'delete_url': reverse('page_speed_and_cwv:page-delete', args=[page.id]),
        })

    return JsonResponse({
        'success': True,
        'created_count': len(created_pages),
        'saved_discovered_ids': saved_discovered_ids,
        'pages': created_pages,
    })

@login_required(login_url='sign-in')
def bulk_delete_discovered_pages_view(request):
    if request.method != 'POST':
        return redirect('page_speed_and_cwv:website-list')

    discovered_page_ids = request.POST.getlist('discovered_page_ids[]') or request.POST.getlist('discovered_page_ids')
    discovered_pages = WebsitePageDiscovery.objects.filter(id__in=discovered_page_ids, created_by=request.user, website__added_by=request.user)
    deleted_page_ids = list(discovered_pages.values_list('id', flat=True))
    discovered_pages.delete()

    return JsonResponse({
        'success': True,
        'deleted_discovered_page_ids': deleted_page_ids,
    })

@login_required(login_url='sign-in')
def discover_pages_view(request):
    if request.method != 'POST':
        return redirect('page_speed_and_cwv:website-list')

    website_id = request.POST.get('website_id')
    website = get_object_or_404(Website, id=website_id, added_by=request.user)

    # Website-url. here we run the crawler to find the urls.
    website_url = website.website_url.strip().lower().rstrip('/')
    root_domain = urlparse(website_url).netloc.lower()
    discovered_urls = {}
    discovered_sources = set()
    error_messages = []
    sitemap_urls = []
    blocked_extensions = (
        '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.ico',
        '.css', '.js', '.json', '.xml', '.txt', '.pdf',
        '.woff', '.woff2', '.ttf', '.eot', '.webmanifest', '.php',
    )
    blocked_paths = (
        '/_next/',
        '/static/',
        '/assets/',
        '/images/',
        '/img/',
        '/css/',
        '/js/',
        '/fonts/',
        '/wp-json/',
    )

    # robots.txt scanning
    try:
        robots_request = Request(f'{website_url}/robots.txt', headers={'User-Agent': 'CoWorkerBot/1.0'})
        with urlopen(robots_request, timeout=DISCOVERY_REQUEST_TIMEOUT) as robots_response:
            robots_content = robots_response.read().decode('utf-8', errors='ignore')

        for line in robots_content.splitlines():
            if line.lower().startswith('sitemap:'):
                sitemap_url = line.split(':', 1)[1].strip()
                if sitemap_url:
                    sitemap_urls.append(sitemap_url)
                    discovered_sources.add('robots')
    except Exception as error:
        error_messages.append(f'Robots fetch failed: {error}')

    # sitemap processing
    if not sitemap_urls:
        sitemap_urls = [
            f'{website_url}/sitemap.xml',
            f'{website_url}/sitemap_index.xml',
        ]

    processed_sitemaps = set()
    sitemap_index = 0

    while sitemap_index < len(sitemap_urls) and len(processed_sitemaps) < 10 and len(discovered_urls) < 200:
        sitemap_url = sitemap_urls[sitemap_index]
        sitemap_index += 1

        if sitemap_url in processed_sitemaps:
            continue

        processed_sitemaps.add(sitemap_url)

        try:
            sitemap_request = Request(sitemap_url, headers={'User-Agent': 'CoWorkerBot/1.0'})
            with urlopen(sitemap_request, timeout=DISCOVERY_REQUEST_TIMEOUT) as sitemap_response:
                sitemap_content = sitemap_response.read()

            sitemap_root = ET.fromstring(sitemap_content)
            discovered_sources.add('sitemap')

            for element in sitemap_root.iter():
                if not element.tag.endswith('loc') or not element.text:
                    continue

                # domain_address + found_url
                found_url = element.text.strip()
                if not urlparse(found_url).scheme:
                    found_url = urljoin(website_url, found_url)

                # eg: /about#contact will remove #contact
                found_url, _fragment = urldefrag(found_url)
                parsed_found_url = urlparse(found_url)

                if parsed_found_url.netloc.lower() != root_domain:
                    continue

                clean_path = parsed_found_url.path.rstrip('/')
                lower_path = clean_path.lower()
                clean_url = f'{parsed_found_url.scheme.lower()}://{parsed_found_url.netloc.lower()}{clean_path}'

                # If the sitemap points to another sitemap file, queue it for processing instead of saving it as a page URL.
                if clean_url.endswith('.xml') or 'sitemap' in clean_url:
                    if clean_url not in processed_sitemaps and clean_url not in sitemap_urls:
                        sitemap_urls.append(clean_url)
                    continue

                if lower_path.endswith(blocked_extensions):
                    continue

                if any(path in lower_path for path in blocked_paths):
                    continue

                discovered_urls[clean_url] = {
                    'page_url': clean_url,
                    'source': 'sitemap',
                }

                if len(discovered_urls) >= 200:
                    break
        except Exception as error:
            error_messages.append(f'Sitemap fetch failed: {sitemap_url} - {error}')

    # if sitemap does not reveal anything then this direct scraping will work
    if not discovered_urls:
        try:
            homepage_request = Request(website_url, headers={'User-Agent': 'CoWorkerBot/1.0'})
            with urlopen(homepage_request, timeout=DISCOVERY_REQUEST_TIMEOUT) as homepage_response:
                homepage_content = homepage_response.read().decode('utf-8', errors='ignore')

            discovered_sources.add('homepage')

            for href in re.findall(r'href=["\\\']([^"\\\']+)["\\\']', homepage_content, flags=re.IGNORECASE):
                if href.startswith(('#', 'mailto:', 'tel:', 'javascript:')):
                    continue

                found_url = urljoin(website_url, href)
                found_url, _fragment = urldefrag(found_url)
                parsed_found_url = urlparse(found_url)

                if parsed_found_url.netloc.lower() != root_domain:
                    continue

                clean_path = parsed_found_url.path.rstrip('/')
                lower_path = clean_path.lower()

                if lower_path.endswith(blocked_extensions):
                    continue

                if any(path in lower_path for path in blocked_paths):
                    continue

                clean_url = f'{parsed_found_url.scheme.lower()}://{parsed_found_url.netloc.lower()}{clean_path}'

                discovered_urls[clean_url] = {
                    'page_url': clean_url,
                    'source': 'homepage',
                }

                if len(discovered_urls) >= 200:
                    break
        except Exception as error:
            error_messages.append(f'Homepage fetch failed: {error}')

    if not discovered_urls:
        messages.error(request, 'No pages could be discovered.')
        return redirect(page_list_redirect(website.id))

    WebsitePageDiscovery.objects.filter(website=website, created_by=request.user).delete()
    discovery_run = WebsitePageDiscoveryRun.objects.create(website=website, created_by=request.user, source_summary=', '.join(sorted(discovered_sources)), error_message='\n'.join(error_messages))

    WebsitePageDiscovery.objects.bulk_create([WebsitePageDiscovery(discovery_run=discovery_run, website=website, created_by=request.user, page_url=item['page_url'], source=item['source']) for item in discovered_urls.values()])

    messages.success(request, f'{len(discovered_urls)} pages discovered successfully.')
    return redirect(page_list_redirect(website.id))


@login_required(login_url='sign-in')
def simple_reports_view(request, website_id=None):
    website = None
    report_indexes = WebsiteSpeedReportAiIndex.objects.filter(
        website__added_by=request.user,
    ).select_related('website').prefetch_related('reports')

    if website_id is not None:
        website = get_object_or_404(
            Website,
            id=website_id,
            added_by=request.user,
        )
        report_indexes = report_indexes.filter(website=website)

    for report_index in report_indexes:
        reports = list(report_index.reports.all())
        report_index.mobile_report = next(
            (report for report in reports if report.device_type == WebsiteSpeedReport.DEVICE_MOBILE),
            None,
        )
        report_index.desktop_report = next(
            (report for report in reports if report.device_type == WebsiteSpeedReport.DEVICE_DESKTOP),
            None,
        )

    context = {
        'website': website,
        'report_indexes': report_indexes,
        'back_to_websites_url': reverse('page_speed_and_cwv:website-list') if website else '',
    }
    return render(request, 'page_speed_and_cwv/reports.html', context)


@login_required(login_url='sign-in')
def simple_report_detail_view(request, website_id, report_index_id):
    website = get_object_or_404(
        Website,
        id=website_id,
        added_by=request.user,
    )
    report_index = get_object_or_404(
        WebsiteSpeedReportAiIndex.objects.prefetch_related('reports'),
        id=report_index_id,
        website=website,
    )
    reports = list(report_index.reports.all())
    mobile_report = next(
        (report for report in reports if report.device_type == WebsiteSpeedReport.DEVICE_MOBILE),
        None,
    )
    desktop_report = next(
        (report for report in reports if report.device_type == WebsiteSpeedReport.DEVICE_DESKTOP),
        None,
    )

    context = {
        'website': website,
        'report_index': report_index,
        'reports': reports,
        'mobile_report': mobile_report,
        'desktop_report': desktop_report,
        'back_to_reports_url': reverse('page_speed_and_cwv:website-reports', args=[website.id]),
    }
    return render(request, 'page_speed_and_cwv/report_detail.html', context)
