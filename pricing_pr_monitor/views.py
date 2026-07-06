from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from .models import PricingPRMonitor, PricingPRRun
from .monitor import mention_record_is_relevant, run_pricing_pr_monitor
from wisoft_co_worker.url_utils import normalize_url


def split_lines(value):
    return [line.strip() for line in (value or '').splitlines() if line.strip()]


def validate_urls(urls):
    validator = URLValidator()
    for url in urls:
        validator(url)


def monitor_queryset(user):
    monitors = list(PricingPRMonitor.objects.filter(added_by=user).prefetch_related('runs'))
    for monitor in monitors:
        runs = list(monitor.runs.all())
        latest_run = runs[0] if runs else None
        monitor.latest_run = latest_run
        monitor.run_count = len(runs)
        monitor.latest_changes_found = latest_run.changes_found if latest_run else 0
        if latest_run:
            monitor.latest_news_mentions_found = sum(
                1
                for mention in latest_run.news_mentions.all()
                if mention_record_is_relevant(mention, monitor)
            )
        else:
            monitor.latest_news_mentions_found = 0
    return monitors


@login_required(login_url='sign-in')
def monitors_view(request):
    context = {
        'monitors': monitor_queryset(request.user),
    }
    return render(request, 'pricing_pr_monitor/monitors.html', context)


@login_required(login_url='sign-in')
def history_view(request):
    runs = PricingPRRun.objects.filter(monitor__added_by=request.user).select_related('monitor', 'requested_by')
    context = {
        'runs': runs,
    }
    return render(request, 'pricing_pr_monitor/history.html', context)


@login_required(login_url='sign-in')
def monitor_detail_view(request, monitor_id):
    monitor = get_object_or_404(PricingPRMonitor, id=monitor_id, added_by=request.user)
    runs = monitor.runs.select_related('requested_by')
    context = {
        'monitor': monitor,
        'runs': runs,
    }
    return render(request, 'pricing_pr_monitor/monitor_detail.html', context)


@login_required(login_url='sign-in')
def monitor_run_view(request, monitor_id=None):
    if request.method != 'POST':
        return redirect('pricing_pr_monitor:monitors')

    if monitor_id is not None:
        monitor = get_object_or_404(PricingPRMonitor, id=monitor_id, added_by=request.user)
    else:
        competitor_name = request.POST.get('competitor_name', '').strip()
        competitor_website = normalize_url(request.POST.get('competitor_website', ''))
        pricing_url = normalize_url(request.POST.get('pricing_url', ''))
        monitored_urls = [normalize_url(url) for url in split_lines(request.POST.get('monitored_urls', ''))]
        news_keywords = split_lines(request.POST.get('news_keywords', ''))
        notes = request.POST.get('notes', '').strip()

        try:
            if not competitor_name:
                raise ValidationError('Competitor name is required.')
            if not competitor_website:
                raise ValidationError('Competitor website is required.')
            urls_to_validate = [competitor_website] + monitored_urls
            if pricing_url:
                urls_to_validate.append(pricing_url)
            validate_urls(urls_to_validate)
        except ValidationError as exc:
            messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
            return redirect('pricing_pr_monitor:monitors')

        monitor = PricingPRMonitor.objects.create(
            competitor_name=competitor_name,
            competitor_website=competitor_website,
            pricing_url=pricing_url,
            monitored_urls=monitored_urls,
            news_keywords=news_keywords,
            notes=notes,
            added_by=request.user,
        )

    run = PricingPRRun.objects.create(monitor=monitor, requested_by=request.user)
    try:
        run_pricing_pr_monitor(run)
    except Exception:
        messages.error(request, 'Pricing & PR monitor run failed. Open the run detail for the error.')
        return redirect('pricing_pr_monitor:run-detail', run.id)

    messages.success(request, 'Pricing & PR monitor run completed successfully.')
    return redirect('pricing_pr_monitor:run-detail', run.id)


@login_required(login_url='sign-in')
def run_detail_view(request, run_id):
    run = get_object_or_404(
        PricingPRRun.objects.select_related('monitor', 'requested_by'),
        id=run_id,
        monitor__added_by=request.user,
    )
    news_mentions = [
        mention
        for mention in run.news_mentions.all()
        if mention_record_is_relevant(mention, run.monitor)
    ]
    context = {
        'run': run,
        'changes': run.changes.select_related('current_snapshot', 'previous_snapshot'),
        'snapshots': run.snapshots.all(),
        'news_mentions': news_mentions,
        'display_news_mentions_count': len(news_mentions),
    }
    return render(request, 'pricing_pr_monitor/run_detail.html', context)


@login_required(login_url='sign-in')
def run_delete_view(request, run_id):
    run = get_object_or_404(
        PricingPRRun.objects.select_related('monitor'),
        id=run_id,
        monitor__added_by=request.user,
    )
    if request.method == 'POST':
        run.delete()
        messages.success(request, 'Pricing & PR monitor run deleted successfully.')
        next_url = request.POST.get('next', '').strip()
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
            return redirect(next_url)
        return redirect('pricing_pr_monitor:history')
    return redirect('pricing_pr_monitor:history')
