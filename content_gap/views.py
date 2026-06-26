from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from .analyzer import run_content_gap_analysis
from .models import ContentGapAnalysis, ContentGapProject


def get_project_queryset(user):
    projects = list(
        ContentGapProject.objects.filter(added_by=user).prefetch_related('analyses')
    )
    for project in projects:
        analyses = list(project.analyses.all())
        latest_analysis = analyses[0] if analyses else None
        project.latest_analysis = latest_analysis
        project.analysis_count = len(analyses)
        project.latest_gap_count = len(latest_analysis.content_gaps or []) if latest_analysis else 0
        project.latest_keyword_count = len(latest_analysis.keyword_opportunities or []) if latest_analysis else 0
    return projects


def validate_url(url, label):
    if not url:
        raise ValidationError(f'{label} is required.')
    URLValidator()(url)


def normalize_url(value):
    """Accept bare domains (e.g. 'example.com/page') by defaulting to https."""
    value = (value or '').strip()
    if value and '://' not in value:
        value = 'https://' + value
    return value


@login_required(login_url='sign-in')
def analysis_form_view(request):
    context = {
        'projects': get_project_queryset(request.user),
    }
    return render(request, 'content_gap/analysis_form.html', context)


@login_required(login_url='sign-in')
def analysis_history_view(request):
    analyses = ContentGapAnalysis.objects.filter(
        project__added_by=request.user,
    ).select_related('project', 'requested_by')
    context = {
        'analyses': analyses,
        'projects': get_project_queryset(request.user),
    }
    return render(request, 'content_gap/history.html', context)


@login_required(login_url='sign-in')
def analysis_run_view(request):
    if request.method != 'POST':
        return redirect('content_gap:analysis')

    own_url = normalize_url(request.POST.get('own_url', ''))
    target_topic = request.POST.get('target_topic', '').strip()
    target_market = request.POST.get('target_market', '').strip()
    notes = request.POST.get('notes', '').strip()
    competitor_urls = [
        normalize_url(request.POST.get(f'competitor_url_{index}', ''))
        for index in range(1, 4)
        if request.POST.get(f'competitor_url_{index}', '').strip()
    ]

    try:
        validate_url(own_url, 'Own page URL')
        if not competitor_urls:
            raise ValidationError('Enter at least one competitor URL.')
        for index, competitor_url in enumerate(competitor_urls, start=1):
            validate_url(competitor_url, f'Competitor URL {index}')
    except ValidationError as exc:
        messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
        return redirect('content_gap:analysis')

    project, _created = ContentGapProject.objects.get_or_create(
        website_url=own_url,
        added_by=request.user,
        defaults={
            'target_topic': target_topic,
            'target_market': target_market,
            'notes': notes,
        },
    )
    changed_fields = []
    for field_name, value in (
        ('target_topic', target_topic),
        ('target_market', target_market),
        ('notes', notes),
    ):
        if value and getattr(project, field_name) != value:
            setattr(project, field_name, value)
            changed_fields.append(field_name)
    if changed_fields:
        changed_fields.append('updated_at')
        project.save(update_fields=changed_fields)

    analysis = ContentGapAnalysis.objects.create(
        project=project,
        requested_by=request.user,
        own_url=own_url,
        competitor_urls=competitor_urls,
    )

    try:
        run_content_gap_analysis(analysis)
    except Exception:
        messages.error(request, 'Content gap analysis failed. Open the result for the error details.')
        return redirect('content_gap:analysis-detail', analysis.id)

    messages.success(request, 'Content gap analysis completed successfully.')
    return redirect('content_gap:analysis-detail', analysis.id)


@login_required(login_url='sign-in')
def analysis_delete_view(request, analysis_id):
    analysis = get_object_or_404(
        ContentGapAnalysis.objects.select_related('project'),
        id=analysis_id,
        project__added_by=request.user,
    )

    if request.method == 'POST':
        analysis.delete()
        messages.success(request, 'Content gap analysis history deleted successfully.')
        next_url = request.POST.get('next', '').strip()
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
            return redirect(next_url)
        return redirect('content_gap:history')

    return redirect('content_gap:history')


@login_required(login_url='sign-in')
def analysis_detail_view(request, analysis_id):
    analysis = get_object_or_404(
        ContentGapAnalysis.objects.select_related('project', 'requested_by'),
        id=analysis_id,
        project__added_by=request.user,
    )
    context = {
        'analysis': analysis,
        'back_to_history_url': reverse('content_gap:history'),
    }
    return render(request, 'content_gap/analysis_detail.html', context)
