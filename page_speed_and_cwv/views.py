from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.http import JsonResponse
from django.urls import reverse
from django.shortcuts import get_object_or_404, redirect, render

from .models import (
    Website,
    WebsitePage,
    WebsiteSpeedReport,
    WebsiteSpeedReportAiIndex,
)

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

    query = Website.objects.filter(
        added_by=request.user,
        website_url__iexact=website_url,
    )

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

        if Website.objects.filter(
            added_by=request.user,
            website_url__iexact=website_url,
        ).exists():
            messages.error(request, 'This website has already been added.')
            return redirect('page_speed_and_cwv:website-list')

        Website.objects.create(
            website_url=website_url,
            note=note,
            is_active=is_active,
            added_by=request.user,
        )

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
        website = get_object_or_404(
            Website,
            id=website_id,
            added_by=request.user,
        )

        if not website_url:
            messages.error(request, 'Website URL is required.')
            return redirect('page_speed_and_cwv:website-list')

        try:
            URLValidator()(website_url)
        except ValidationError:
            messages.error(request, 'Enter a valid website URL.')
            return redirect('page_speed_and_cwv:website-list')

        if Website.objects.filter(
            added_by=request.user,
            website_url__iexact=website_url,
        ).exclude(id=website.id).exists():
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
    website = get_object_or_404(
        Website,
        id=website_id,
        added_by=request.user,
    )

    if request.method == 'POST':
        website.delete()
        messages.success(request, 'Record deleted successfully.')
        return redirect('page_speed_and_cwv:website-list')

    return redirect('page_speed_and_cwv:website-list')

@login_required(login_url='sign-in')
def reports_view(request, website_id=None):
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
def report_detail_view(request, website_id, report_index_id):
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
        'back_to_overview_url': reverse('page_speed_and_cwv:website-overview', args=[website.id]),
    }
    return render(request, 'page_speed_and_cwv/report_detail.html', context)

@login_required(login_url='sign-in')
def list_pages_view(request):
    website = None
    website_id = request.GET.get('website_id')

    if website_id:
        website = get_object_or_404(
            Website,
            id=website_id,
            added_by=request.user,
        )

    context = {
        'website': website,
        'pages': website.pages.all() if website else [],
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

    query = WebsitePage.objects.filter(
        website_id=website_id,
        website__added_by=request.user,
        page_url__iexact=page_url,
    )

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

    website = get_object_or_404(
        Website,
        id=website_id,
        added_by=request.user,
    )

    if not page_url:
        messages.error(request, 'Page URL is required.')
        return redirect(page_list_redirect(website.id))

    try:
        URLValidator()(page_url)
    except ValidationError:
        messages.error(request, 'Enter a valid page URL.')
        return redirect(page_list_redirect(website.id))

    if WebsitePage.objects.filter(
        website=website,
        page_url__iexact=page_url,
    ).exists():
        messages.error(request, 'This page has already been added.')
        return redirect(page_list_redirect(website.id))

    WebsitePage.objects.create(
        website=website,
        page_url=page_url,
        is_active=is_active,
    )
    messages.success(request, 'Record inserted successfully.')
    return redirect(page_list_redirect(website.id))


@login_required(login_url='sign-in')
def update_page_view(request):
    if request.method != 'POST':
        return redirect('page_speed_and_cwv:website-list')

    page_id = request.POST.get('page_id')
    page_url = request.POST.get('page_url', '').strip().lower()
    is_active = request.POST.get('is_active') == '1'

    page = get_object_or_404(
        WebsitePage.objects.select_related('website'),
        id=page_id,
        website__added_by=request.user,
    )

    if not page_url:
        messages.error(request, 'Page URL is required.')
        return redirect(page_list_redirect(page.website.id))

    try:
        URLValidator()(page_url)
    except ValidationError:
        messages.error(request, 'Enter a valid page URL.')
        return redirect(page_list_redirect(page.website.id))

    if WebsitePage.objects.filter(
        website=page.website,
        page_url__iexact=page_url,
    ).exclude(id=page.id).exists():
        messages.error(request, 'This page has already been added.')
        return redirect(page_list_redirect(page.website.id))

    page.page_url = page_url
    page.is_active = is_active
    page.save()
    messages.success(request, 'Record updated successfully.')
    return redirect(page_list_redirect(page.website.id))


@login_required(login_url='sign-in')
def delete_page_view(request, page_id):
    page = get_object_or_404(
        WebsitePage.objects.select_related('website'),
        id=page_id,
        website__added_by=request.user,
    )

    if request.method == 'POST':
        website_id = page.website.id
        page.delete()
        messages.success(request, 'Record deleted successfully.')
        return redirect(page_list_redirect(website_id))

    return redirect(page_list_redirect(page.website.id))
