from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from .models import KeywordResearchProject, KeywordResearchRun
from .research import run_keyword_research


def project_queryset(user):
    projects = list(KeywordResearchProject.objects.filter(added_by=user).prefetch_related('runs'))
    for project in projects:
        runs = list(project.runs.all())
        latest_run = runs[0] if runs else None
        project.latest_run = latest_run
        project.run_count = len(runs)
        project.latest_keywords_count = latest_run.keyword_ideas.count() if latest_run else 0
        project.latest_planner_count = latest_run.planner_metrics.count() if latest_run else 0
    return projects


@login_required(login_url='sign-in')
def research_view(request):
    return render(request, 'keyword_research/research.html', {'projects': project_queryset(request.user)})


@login_required(login_url='sign-in')
def history_view(request):
    runs = KeywordResearchRun.objects.filter(project__added_by=request.user).select_related('project', 'requested_by')
    return render(request, 'keyword_research/history.html', {'runs': runs})


def decorate_planner_metric(metric):
    searches = metric.avg_monthly_searches or 0
    if searches >= 1000:
        metric.search_badge_class = 'success'
    elif searches >= 100:
        metric.search_badge_class = 'warning'
    elif searches:
        metric.search_badge_class = 'primary'
    else:
        metric.search_badge_class = 'secondary'

    competition = (metric.competition or '').upper()
    if competition == 'HIGH':
        metric.competition_badge_class = 'danger'
    elif competition == 'MEDIUM':
        metric.competition_badge_class = 'warning'
    elif competition == 'LOW':
        metric.competition_badge_class = 'success'
    else:
        metric.competition_badge_class = 'secondary'

    index = metric.competition_index
    if index is None:
        metric.index_badge_class = 'secondary'
    elif index >= 67:
        metric.index_badge_class = 'danger'
    elif index >= 34:
        metric.index_badge_class = 'warning'
    else:
        metric.index_badge_class = 'success'

    bid = metric.high_top_of_page_bid or metric.low_top_of_page_bid
    if bid is None:
        metric.bid_badge_class = 'secondary'
    elif bid >= 20:
        metric.bid_badge_class = 'danger'
    elif bid >= 5:
        metric.bid_badge_class = 'warning'
    else:
        metric.bid_badge_class = 'info'
    return metric


@login_required(login_url='sign-in')
def run_research_view(request):
    if request.method != 'POST':
        return redirect('keyword_research:research')

    website_url = request.POST.get('website_url', '').strip()
    # Accept bare domains (e.g. "example.com") by defaulting to https.
    if website_url and '://' not in website_url:
        website_url = 'https://' + website_url
    target_location = request.POST.get('target_location', '').strip()
    language = request.POST.get('language', '').strip()
    seed_topic = request.POST.get('seed_topic', '').strip()
    notes = request.POST.get('notes', '').strip()
    max_pages_raw = request.POST.get('max_pages', '20')

    try:
        if not website_url:
            raise ValidationError('Website URL is required.')
        if not target_location:
            raise ValidationError('Target location is required.')
        URLValidator()(website_url)
    except ValidationError as exc:
        messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
        return redirect('keyword_research:research')

    try:
        max_pages = int(max_pages_raw)
    except (TypeError, ValueError):
        max_pages = 20
    max_pages = max(1, min(max_pages, 50))

    project = KeywordResearchProject.objects.create(
        website_url=website_url,
        target_location=target_location,
        language=language,
        seed_topic=seed_topic,
        notes=notes,
        added_by=request.user,
    )
    run = KeywordResearchRun.objects.create(
        project=project,
        requested_by=request.user,
        max_pages=max_pages,
    )

    try:
        run_keyword_research(run)
    except Exception:
        messages.error(request, 'Keyword research failed. Open the detail page for the error.')
        return redirect('keyword_research:detail', run.id)

    messages.success(request, 'Keyword research completed successfully.')
    return redirect('keyword_research:detail', run.id)


@login_required(login_url='sign-in')
def detail_view(request, run_id):
    run = get_object_or_404(
        KeywordResearchRun.objects.select_related('project', 'requested_by'),
        id=run_id,
        project__added_by=request.user,
    )
    planner_metrics = [decorate_planner_metric(metric) for metric in run.planner_metrics.all()]
    return render(request, 'keyword_research/detail.html', {
        'run': run,
        'keyword_ideas': run.keyword_ideas.all(),
        'clusters': run.clusters.all(),
        'planner_metrics': planner_metrics,
        'pages': run.pages.all(),
    })


@login_required(login_url='sign-in')
def delete_run_view(request, run_id):
    run = get_object_or_404(
        KeywordResearchRun.objects.select_related('project'),
        id=run_id,
        project__added_by=request.user,
    )
    if request.method == 'POST':
        run.delete()
        messages.success(request, 'Keyword research run deleted successfully.')
        next_url = request.POST.get('next', '').strip()
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
            return redirect(next_url)
        return redirect('keyword_research:history')
    return redirect('keyword_research:history')
