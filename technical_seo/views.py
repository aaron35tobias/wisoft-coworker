from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.http import JsonResponse

from .models import TechnicalSEOAudit, TechnicalSEOIssue, TechnicalSEOWebsite
from .tasks import run_technical_seo_audit_task
from wisoft_co_worker.task_utils import enqueue_background_task


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
    if not website_url:
        messages.error(request, 'Website URL is required.')
        return redirect('technical_seo:audits')

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
    )

    queued = enqueue_background_task(
        run_technical_seo_audit_task,
        audit,
        'Technical SEO audit could not be queued',
    )
    if queued:
        messages.success(request, 'Technical SEO audit started. This page will update when the crawl completes.')
    else:
        messages.error(request, 'Technical SEO audit could not be queued. Check Redis/Celery and open the detail page for the error.')
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
    gsc_inspections = audit.gsc_url_inspections.select_related('page')
    issue_type_counts = list(issues.values('issue_type').annotate(total=Count('id')).order_by('-total', 'issue_type'))
    for row in issue_type_counts:
        row['label'] = row['issue_type'].replace('_', ' ').title()

    severity_filter = request.GET.get('severity', '').strip()
    if severity_filter:
        issues = issues.filter(severity=severity_filter)

    gsc_inspection_verdict = request.GET.get('gsc_verdict', '').strip()
    if gsc_inspection_verdict:
        gsc_inspections = gsc_inspections.filter(verdict=gsc_inspection_verdict)

    context = {
        'audit': audit,
        'issues': issues,
        'pages': pages,
        'gsc_inspections': gsc_inspections,
        'gsc_filters': {
            'verdict': gsc_inspection_verdict,
        },
        'gsc_verdicts': audit.gsc_url_inspections.exclude(verdict='').values_list('verdict', flat=True).distinct().order_by('verdict'),
        'issue_type_counts': issue_type_counts,
        'ai_summary_sections': parse_ai_summary_sections(audit.ai_summary) if audit.ai_summary else [],
        'severity_filter': severity_filter,
        'severity_choices': TechnicalSEOIssue.SEVERITY_CHOICES,
        'back_to_audits_url': reverse('technical_seo:history'),
    }
    return render(request, 'technical_seo/audit_detail.html', context)

@login_required(login_url='sign-in')
def audit_status_view(request, audit_id):
    audit = get_object_or_404(
        TechnicalSEOAudit,
        id=audit_id,
        website__added_by=request.user,
    )

    return JsonResponse({
        "status": audit.status,
        "pages_crawled": audit.pages_crawled,
        "issues_found": audit.issues_found,
        "detail_url": reverse("technical_seo:audit-detail", args=[audit.id]),
    })
