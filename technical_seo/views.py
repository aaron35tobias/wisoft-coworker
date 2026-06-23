from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.utils.http import url_has_allowed_host_and_scheme

from .models import TechnicalSEOAudit, TechnicalSEOIssue, TechnicalSEOWebsite
from .seo_audit import run_technical_seo_audit


def get_website_dashboard_queryset(user):
    websites = list(
        TechnicalSEOWebsite.objects.filter(added_by=user, is_active=True)
        .prefetch_related('technical_seo_audits')
    )
    for website in websites:
        audits = list(website.technical_seo_audits.all())
        latest_audit = audits[0] if audits else None
        website.latest_audit = latest_audit
        website.audit_count = len(audits)
        website.latest_issues_found = latest_audit.issues_found if latest_audit else 0
        website.latest_pages_crawled = latest_audit.pages_crawled if latest_audit else 0
    return websites


def parse_ai_summary_sections(summary):
    sections = []
    current_title = 'Summary'
    current_lines = []

    for raw_line in summary.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        normalized = line.strip('*#:- ')
        is_heading = (
            len(normalized) <= 60
            and not normalized.endswith('.')
            and any(keyword in normalized.lower() for keyword in [
                'executive summary',
                'top priorities',
                'corrective actions',
                'developer notes',
                'summary',
                'priorities',
                'actions',
                'notes',
            ])
        )

        if is_heading:
            if current_lines:
                sections.append({
                    'title': current_title,
                    'body': '\n'.join(current_lines),
                })
            current_title = normalized
            current_lines = []
        else:
            current_lines.append(line.lstrip('- '))

    if current_lines:
        sections.append({
            'title': current_title,
            'body': '\n'.join(current_lines),
        })

    return sections[:6]


@login_required(login_url='sign-in')
def audits_view(request, website_id=None):
    website = None
    websites = get_website_dashboard_queryset(request.user)

    if website_id is not None:
        website = get_object_or_404(
            TechnicalSEOWebsite,
            id=website_id,
            added_by=request.user,
        )

    context = {
        'website': website,
        'websites': websites,
    }
    return render(request, 'technical_seo/audits.html', context)


@login_required(login_url='sign-in')
def audit_history_view(request, website_id=None):
    website = None
    audits = TechnicalSEOAudit.objects.filter(
        website__added_by=request.user,
    ).select_related('website', 'requested_by')
    websites = get_website_dashboard_queryset(request.user)

    if website_id is not None:
        website = get_object_or_404(
            TechnicalSEOWebsite,
            id=website_id,
            added_by=request.user,
        )
        audits = audits.filter(website=website)

    context = {
        'website': website,
        'websites': websites,
        'audits': audits,
    }
    return render(request, 'technical_seo/audit_history.html', context)


@login_required(login_url='sign-in')
def audit_run_view(request):
    if request.method != 'POST':
        return redirect('technical_seo:audits')

    website_url = request.POST.get('website_url', '').strip()
    note = request.POST.get('note', '').strip()
    max_pages_raw = request.POST.get('max_pages', '50')
    gsc_start_date = parse_date(request.POST.get('gsc_start_date', '').strip())
    gsc_end_date = parse_date(request.POST.get('gsc_end_date', '').strip())
    gsc_country_filter = request.POST.get('gsc_country_filter', '').strip().upper()
    gsc_device_filter = request.POST.get('gsc_device_filter', '').strip().upper()

    if not website_url:
        messages.error(request, 'Website URL is required.')
        return redirect('technical_seo:audits')

    # Accept bare domains (e.g. "nike.com") by defaulting to https.
    if '://' not in website_url:
        website_url = 'https://' + website_url

    try:
        URLValidator()(website_url)
    except ValidationError:
        messages.error(request, 'Enter a valid website URL.')
        return redirect('technical_seo:audits')

    try:
        max_pages = int(max_pages_raw)
    except (TypeError, ValueError):
        max_pages = 50
    max_pages = max(1, min(max_pages, 100))

    website, _created = TechnicalSEOWebsite.objects.get_or_create(
        website_url=website_url,
        added_by=request.user,
        defaults={
            'note': note,
            'is_active': True,
        },
    )
    if note and website.note != note:
        website.note = note
        website.save(update_fields=['note', 'date_modified'])

    audit = TechnicalSEOAudit.objects.create(
        website=website,
        requested_by=request.user,
        max_pages=max_pages,
        gsc_start_date=gsc_start_date,
        gsc_end_date=gsc_end_date,
        gsc_country_filter=gsc_country_filter[:20],
        gsc_device_filter=gsc_device_filter[:20],
    )

    try:
        run_technical_seo_audit(audit)
    except Exception:
        messages.error(request, 'Technical SEO audit failed. Open the audit detail for the error message.')
        return redirect('technical_seo:audit-detail', audit.id)

    messages.success(request, 'Technical SEO audit completed successfully.')
    return redirect('technical_seo:audit-detail', audit.id)


@login_required(login_url='sign-in')
def audit_delete_view(request, audit_id):
    audit = get_object_or_404(
        TechnicalSEOAudit.objects.select_related('website'),
        id=audit_id,
        website__added_by=request.user,
    )

    if request.method == 'POST':
        website_id = audit.website_id
        audit.delete()
        messages.success(request, 'Technical SEO audit history deleted successfully.')
        next_url = request.POST.get('next', '').strip()
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
            return redirect(next_url)
        return redirect('technical_seo:website-history', website_id)

    return redirect('technical_seo:history')


@login_required(login_url='sign-in')
def audit_detail_view(request, audit_id):
    audit = get_object_or_404(
        TechnicalSEOAudit.objects.select_related('website', 'requested_by'),
        id=audit_id,
        website__added_by=request.user,
    )
    issues = audit.issues.select_related('page')
    pages = audit.pages.all()
    gsc_rows = audit.gsc_rows.all()
    gsc_inspections = audit.gsc_url_inspections.select_related('page')
    issue_type_counts = list(issues.values('issue_type').annotate(total=Count('id')).order_by('-total', 'issue_type'))
    for row in issue_type_counts:
        row['label'] = row['issue_type'].replace('_', ' ').title()

    severity_filter = request.GET.get('severity', '').strip()
    if severity_filter:
        issues = issues.filter(severity=severity_filter)

    gsc_country = request.GET.get('gsc_country', '').strip().upper()
    gsc_device = request.GET.get('gsc_device', '').strip().upper()
    gsc_query = request.GET.get('gsc_query', '').strip()
    gsc_page = request.GET.get('gsc_page', '').strip()
    if gsc_country:
        gsc_rows = gsc_rows.filter(country=gsc_country)
    if gsc_device:
        gsc_rows = gsc_rows.filter(device=gsc_device)
    if gsc_query:
        gsc_rows = gsc_rows.filter(query__icontains=gsc_query)
    if gsc_page:
        gsc_rows = gsc_rows.filter(page_url__icontains=gsc_page)

    gsc_inspection_verdict = request.GET.get('gsc_verdict', '').strip()
    if gsc_inspection_verdict:
        gsc_inspections = gsc_inspections.filter(verdict=gsc_inspection_verdict)

    context = {
        'audit': audit,
        'issues': issues,
        'pages': pages,
        'gsc_rows': gsc_rows,
        'gsc_inspections': gsc_inspections,
        'gsc_filters': {
            'country': gsc_country,
            'device': gsc_device,
            'query': gsc_query,
            'page': gsc_page,
            'verdict': gsc_inspection_verdict,
        },
        'gsc_countries': audit.gsc_rows.exclude(country='').values_list('country', flat=True).distinct().order_by('country'),
        'gsc_devices': audit.gsc_rows.exclude(device='').values_list('device', flat=True).distinct().order_by('device'),
        'gsc_verdicts': audit.gsc_url_inspections.exclude(verdict='').values_list('verdict', flat=True).distinct().order_by('verdict'),
        'issue_type_counts': issue_type_counts,
        'ai_summary_sections': parse_ai_summary_sections(audit.ai_summary) if audit.ai_summary else [],
        'severity_filter': severity_filter,
        'severity_choices': TechnicalSEOIssue.SEVERITY_CHOICES,
        'back_to_audits_url': reverse('technical_seo:history'),
    }
    return render(request, 'technical_seo/audit_detail.html', context)
