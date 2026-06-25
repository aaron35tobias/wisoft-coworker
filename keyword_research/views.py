from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from .models import KeywordCartItem, KeywordResearchProject, KeywordResearchRun
from .tasks import run_keyword_research_task
from wisoft_co_worker.task_utils import enqueue_background_task


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
    seed_keywords = request.POST.get('seed_keywords', '').strip()
    target_location = request.POST.get('target_location', '').strip()
    language = request.POST.get('language', '').strip()
    seed_topic = request.POST.get('seed_topic', '').strip()
    notes = request.POST.get('notes', '').strip()

    try:
        if not website_url and not seed_keywords:
            raise ValidationError('Enter either a Page URL or keywords.')
        if not target_location:
            raise ValidationError('Target location is required.')
        if website_url:
            URLValidator()(website_url)
    except ValidationError as exc:
        messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
        return redirect('keyword_research:research')

    project = KeywordResearchProject.objects.create(
        website_url=website_url,
        seed_keywords=seed_keywords,
        target_location=target_location,
        language=language,
        seed_topic=seed_topic,
        notes=notes,
        added_by=request.user,
    )
    run = KeywordResearchRun.objects.create(
        project=project,
        requested_by=request.user,
        max_pages=1,
    )

    queued = enqueue_background_task(
        run_keyword_research_task,
        run,
        'Keyword research could not be queued',
    )
    if queued:
        messages.success(request, 'Keyword research started. This page will update when the research completes.')
    else:
        messages.error(request, 'Keyword research could not be queued. Check Redis/Celery and open the detail page for the error.')
    return redirect('keyword_research:detail', run.id)


@login_required(login_url='sign-in')
def detail_view(request, run_id):
    run = get_object_or_404(
        KeywordResearchRun.objects.select_related('project', 'requested_by'),
        id=run_id,
        project__added_by=request.user,
    )
    planner_metrics = [decorate_planner_metric(metric) for metric in run.planner_metrics.all()]
    cart_items = list(run.cart_items.filter(user=request.user))
    return render(request, 'keyword_research/detail.html', {
        'run': run,
        'keyword_ideas': run.keyword_ideas.all(),
        'clusters': run.clusters.all(),
        'planner_metrics': planner_metrics,
        'pages': run.pages.all(),
        'cart_items': cart_items,
        'cart_keyword_values': [item.keyword.lower() for item in cart_items],
    })


@login_required(login_url='sign-in')
@require_POST
def add_cart_keyword_view(request, run_id):
    run = get_object_or_404(
        KeywordResearchRun,
        id=run_id,
        project__added_by=request.user,
    )
    keyword = request.POST.get('keyword', '').strip()
    source = request.POST.get('source', '').strip()
    if not keyword:
        return JsonResponse({'success': False, 'error': 'Keyword is required.'}, status=400)

    item = KeywordCartItem.objects.filter(
        run=run,
        user=request.user,
        keyword__iexact=keyword,
    ).first()
    if item is None:
        item = KeywordCartItem.objects.create(
            run=run,
            user=request.user,
            keyword=keyword[:255],
            source=source[:20],
        )
    elif source and not item.source:
        item.source = source[:20]
        item.save(update_fields=['source'])

    return JsonResponse({
        'success': True,
        'keyword': item.keyword,
        'source': item.source,
        'cart_count': run.cart_items.filter(user=request.user).count(),
    })


@login_required(login_url='sign-in')
@require_POST
def remove_cart_keyword_view(request, run_id):
    run = get_object_or_404(
        KeywordResearchRun,
        id=run_id,
        project__added_by=request.user,
    )
    keyword = request.POST.get('keyword', '').strip()
    if not keyword:
        return JsonResponse({'success': False, 'error': 'Keyword is required.'}, status=400)

    KeywordCartItem.objects.filter(
        run=run,
        user=request.user,
        keyword__iexact=keyword,
    ).delete()

    return JsonResponse({
        'success': True,
        'keyword': keyword,
        'cart_count': run.cart_items.filter(user=request.user).count(),
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

@login_required(login_url='sign-in')
@require_GET
def keyword_run_status_view(request, run_id):
    run = get_object_or_404(
        KeywordResearchRun.objects.only(
            'id',
            'status',
            'pages_crawled',
            'planner_status',
            'error_message',
        ),
        id=run_id,
        project__added_by=request.user,
    )

    return JsonResponse({
        'status': str(run.status).lower().strip(),
        'pages_crawled': run.pages_crawled or 0,
        'planner_status': run.planner_status or '',
        'keyword_ideas_count': run.keyword_ideas.count(),
        'clusters_count': run.clusters.count(),
        'planner_metrics_count': run.planner_metrics.count(),
        'detail_url': reverse('keyword_research:detail', args=[run.id]),
    })
