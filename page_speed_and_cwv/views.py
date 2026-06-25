from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.http import JsonResponse
from django.urls import reverse
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
    WebsiteSpeedReportAiIndex,
)

DISCOVERY_REQUEST_TIMEOUT = 15

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
    report_indexes = WebsiteSpeedReportAiIndex.objects.filter(website__added_by=request.user).select_related('website').prefetch_related('reports')

    if website_id is not None:
        website = get_object_or_404(Website, id=website_id, added_by=request.user)
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
def report_detail_view(request, website_id, report_index_id):
    website = get_object_or_404(Website, id=website_id, added_by=request.user)
    report_index = get_object_or_404(WebsiteSpeedReportAiIndex.objects.prefetch_related('reports'), id=report_index_id, website=website)
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
        'back_to_overview_url': reverse('page_speed_and_cwv:website-overview', args=[website.id]),
    }
    return render(request, 'page_speed_and_cwv/report_detail.html', context)

@login_required(login_url='sign-in')
def list_pages_view(request):
    website = None
    website_id = request.GET.get('website_id')

    if website_id:
        website = get_object_or_404(Website, id=website_id, added_by=request.user)

    context = {
        'website': website,
        'pages': website.pages.all() if website else [],
        'discovered_pages': website.page_discoveries.all() if website else [],
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
        '.css', '.js', '.json', '.txt', '.pdf',
        '.woff', '.woff2', '.ttf', '.eot', '.webmanifest', '.php'
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
        '/wp-json/'
    )

    #robots txt scanning
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

    #sitemap processing txt scanning
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

                #domain_address + found_url
                found_url = element.text.strip()
                if not urlparse(found_url).scheme:
                    found_url = urljoin(website_url, found_url)

                #eg: /about#contact will remove #contact
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
    
    #if sitemap does not reveal anything then this direct scraping will work
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
