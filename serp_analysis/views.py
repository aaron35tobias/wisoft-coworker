from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from .analyzer import normalize_url, run_serp_analysis
from .models import SERPAnalysis


SCORE_LABELS = [
    ('overall', 'Overall'),
    ('content', 'Content'),
    ('meta', 'Meta'),
    ('technical', 'Technical'),
    ('media_schema', 'Media / Schema'),
    ('links', 'Links'),
    ('pagespeed', 'PageSpeed'),
]


def parse_ai_summary_sections(summary):
    sections = []
    current_title = 'Summary'
    current_lines = []
    heading_keywords = [
        'executive summary',
        'summary',
        'content strategy',
        'competitor strategy',
        'serp opportunities',
        'opportunities',
        'technical findings',
        'technical',
        'meta',
        'canonical',
        'page speed',
        'recommendations',
        'actions',
    ]

    for raw_line in (summary or '').splitlines():
        line = raw_line.strip()
        if not line:
            continue
        normalized = line.strip('*#:- ')
        is_heading = (
            len(normalized) <= 70
            and not normalized.endswith('.')
            and any(keyword in normalized.lower() for keyword in heading_keywords)
        )
        if is_heading:
            if current_lines:
                sections.append({'title': current_title, 'body': '\n'.join(current_lines)})
            current_title = normalized
            current_lines = []
        else:
            current_lines.append(line.lstrip('- '))

    if current_lines:
        sections.append({'title': current_title, 'body': '\n'.join(current_lines)})
    return sections[:6]


def validate_url(value, label, required=False):
    value = (value or '').strip()
    if not value and required:
        raise ValidationError(f'{label} is required.')
    if not value:
        return ''
    normalized = normalize_url(value)
    URLValidator()(normalized)
    return normalized


@login_required(login_url='sign-in')
def analysis_view(request):
    analyses = SERPAnalysis.objects.filter(requested_by=request.user)[:8]
    return render(request, 'serp_analysis/analysis.html', {'analyses': analyses})


@login_required(login_url='sign-in')
def history_view(request):
    analyses = SERPAnalysis.objects.filter(requested_by=request.user)
    return render(request, 'serp_analysis/history.html', {'analyses': analyses})


def average_metric(snapshots, key):
    values = [snapshot.get(key) or 0 for snapshot in snapshots]
    if not values:
        return 0
    return round(sum(values) / len(values), 1)


def yes_no_average(snapshots, key):
    if not snapshots:
        return '0%'
    total = sum(1 for snapshot in snapshots if snapshot.get(key))
    return f'{round((total / len(snapshots)) * 100)}%'


def average_score(snapshots, key):
    values = [
        (snapshot.get('scores') or {}).get(key)
        for snapshot in snapshots
    ]
    values = [value for value in values if isinstance(value, (int, float))]
    if not values:
        return 0
    return round(sum(values) / len(values), 1)


def score_status(own_score, competitor_score):
    if own_score >= competitor_score:
        return 'Ahead'
    if own_score >= competitor_score - 5:
        return 'Close'
    return 'Behind'


def build_scorecard_rows(analysis):
    own_scores = (analysis.target_snapshot or {}).get('scores') or {}
    competitors = analysis.competitor_snapshots or []
    rows = []
    for key, label in SCORE_LABELS:
        own_score = own_scores.get(key, 0)
        competitor_score = average_score(competitors, key)
        rows.append({
            'metric': label,
            'own': own_score,
            'competitors': competitor_score,
            'gap': round(own_score - competitor_score, 1),
            'status': score_status(own_score, competitor_score),
        })
    return rows


def build_comparison_rows(analysis):
    own = analysis.target_snapshot or {}
    competitors = analysis.competitor_snapshots or []
    return [
        {
            'metric': 'Word Count',
            'own': own.get('word_count', 0),
            'competitors': average_metric(competitors, 'word_count'),
        },
        {
            'metric': 'Images',
            'own': own.get('image_count', 0),
            'competitors': average_metric(competitors, 'image_count'),
        },
        {
            'metric': 'Videos',
            'own': own.get('video_count', 0),
            'competitors': average_metric(competitors, 'video_count'),
        },
        {
            'metric': 'Internal Links',
            'own': own.get('internal_links_count', 0),
            'competitors': average_metric(competitors, 'internal_links_count'),
        },
        {
            'metric': 'External Links',
            'own': own.get('external_links_count', 0),
            'competitors': average_metric(competitors, 'external_links_count'),
        },
        {
            'metric': 'PageSpeed Score',
            'own': own.get('performance_score', 0),
            'competitors': average_metric(competitors, 'performance_score'),
        },
        {
            'metric': 'Canonical Present',
            'own': 'Yes' if own.get('canonical_url') else 'No',
            'competitors': yes_no_average(competitors, 'canonical_url'),
        },
        {
            'metric': 'Meta Description Present',
            'own': 'Yes' if own.get('meta_description') else 'No',
            'competitors': yes_no_average(competitors, 'meta_description'),
        },
        {
            'metric': 'H1 Count',
            'own': len(own.get('h1') or []),
            'competitors': average_metric([{'h1_count': len(snapshot.get('h1') or [])} for snapshot in competitors], 'h1_count'),
        },
    ]


@login_required(login_url='sign-in')
def run_analysis_view(request):
    if request.method != 'POST':
        return redirect('serp_analysis:analysis')

    keyword = request.POST.get('keyword', '').strip()
    location = request.POST.get('location', '').strip()
    target_url_raw = request.POST.get('target_url', '').strip()
    competitor_urls_raw = [
        request.POST.get(f'competitor_url_{index}', '').strip()
        for index in range(1, 6)
        if request.POST.get(f'competitor_url_{index}', '').strip()
    ]

    try:
        if not keyword:
            raise ValidationError('Target keyword is required.')
        target_url = validate_url(target_url_raw, 'Own target URL', required=True)
        if not competitor_urls_raw:
            raise ValidationError('Enter at least one competitor SERP URL.')
        competitor_urls = [
            validate_url(url, f'Competitor URL {index}', required=True)
            for index, url in enumerate(competitor_urls_raw, start=1)
        ]
    except ValidationError as exc:
        messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
        return redirect('serp_analysis:analysis')

    analysis = SERPAnalysis.objects.create(
        keyword=keyword,
        location=location,
        target_url=target_url,
        competitor_urls=competitor_urls,
        requested_by=request.user,
    )

    try:
        run_serp_analysis(analysis)
    except Exception:
        messages.error(request, 'SERP analysis failed. Open the result for details.')
        return redirect('serp_analysis:detail', analysis.id)

    messages.success(request, 'SERP analysis completed successfully.')
    return redirect('serp_analysis:detail', analysis.id)


@login_required(login_url='sign-in')
def detail_view(request, analysis_id):
    analysis = get_object_or_404(SERPAnalysis, id=analysis_id, requested_by=request.user)
    return render(request, 'serp_analysis/detail.html', {
        'analysis': analysis,
        'scorecard_rows': build_scorecard_rows(analysis),
        'comparison_rows': build_comparison_rows(analysis),
        'ai_summary_sections': parse_ai_summary_sections(analysis.ai_summary),
        'back_to_history_url': reverse('serp_analysis:history'),
    })


@login_required(login_url='sign-in')
def delete_view(request, analysis_id):
    analysis = get_object_or_404(SERPAnalysis, id=analysis_id, requested_by=request.user)
    if request.method == 'POST':
        analysis.delete()
        messages.success(request, 'SERP analysis deleted successfully.')
        next_url = request.POST.get('next', '').strip()
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
            return redirect(next_url)
        return redirect('serp_analysis:history')
    return redirect('serp_analysis:history')
