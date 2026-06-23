from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.urls import reverse
from django.shortcuts import get_object_or_404, redirect, render

from .models import (
    Website,
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
def create_view(request):
    if request.method == 'POST':
        website_url = request.POST.get('website_url', '').strip()
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
        website_url = request.POST.get('website_url', '').strip()
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
        'back_to_reports_url': reverse('page_speed_and_cwv:website-reports', args=[website.id]),
    }
    return render(request, 'page_speed_and_cwv/report_detail.html', context)
