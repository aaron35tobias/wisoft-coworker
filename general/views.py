import os
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
import anthropic

from technical_seo.models import TechnicalSEOAudit
from page_speed_and_cwv.models import WebsiteSpeedReport


def _domain(url):
    return url.split('://', 1)[-1].rstrip('/') if url else ''


def _build_technical_seo(user):
    """Latest Technical SEO audit + a computed health score for the gauge."""
    audit = (
        TechnicalSEOAudit.objects
        .filter(requested_by=user)
        .select_related('website')
        .order_by('-started_at')
        .first()
    )
    if not audit:
        return None

    score = max(0, 100 - audit.critical_issues * 20 - audit.high_issues * 8
                - audit.medium_issues * 3 - audit.low_issues * 1)
    if score >= 80:
        label, color = 'Good', '#50CD89'
    elif score >= 50:
        label, color = 'Fair', '#FFC700'
    else:
        label, color = 'Poor', '#F1416C'

    return {
        'audit_id': audit.id,
        'domain': _domain(audit.website.website_url),
        'status': audit.get_status_display(),
        'pages': audit.pages_crawled,
        'issues': audit.issues_found,
        'critical': audit.critical_issues,
        'high': audit.high_issues,
        'started': audit.started_at,
        'health_score': score,
        'health_label': label,
        'health_color': color,
    }


def _build_page_speed(user):
    """Latest Page Speed report, if the user has run one."""
    speed = (
        WebsiteSpeedReport.objects
        .filter(website__added_by=user)
        .select_related('website')
        .order_by('-scanned_at')
        .first()
    )
    if not speed:
        return None
    return {
        'domain': _domain(speed.website.website_url),
        'performance': speed.performance_score,
        'seo': speed.seo_score,
        'lcp': speed.largest_contentful_paint,
        'cls': speed.cumulative_layout_shift,
    }


@login_required(login_url='sign-in')
def dashboard_view(request):
    context = {
        'tech': _build_technical_seo(request.user),
        'speed': _build_page_speed(request.user),
    }
    return render(request, 'general/dashboard.html', context)

@login_required(login_url='sign-in')
def billing_view(request):
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    # Using sonnet model
    model = os.environ.get('ANTHROPIC_MODEL', 'claude-3-5-sonnet-20240620')
    
    usage_data = None
    error = None
    
    if api_key and api_key != 'xxx':
        try:
            client = anthropic.Anthropic(api_key=api_key)
            # Make a simple demo call to get token usage
            response = client.messages.create(
                model=model,
                max_tokens=50,
                messages=[
                    {"role": "user", "content": "Hello, this is a test to check token usage."}
                ]
            )
            # Claude limits usually depend on tiers, we mock a limit for the demo
            total_used = response.usage.input_tokens + response.usage.output_tokens
            limit = 50000
            
            usage_data = {
                'input_tokens': response.usage.input_tokens,
                'output_tokens': response.usage.output_tokens,
                'total_tokens': total_used,
                'limit': limit,
                'remaining': limit - total_used,
                'usage_percent': (total_used / limit) * 100
            }
        except Exception as e:
            error = str(e)
    else:
        # Mock data if the key is 'xxx' or missing
        limit = 50000
        total_used = 16000
        usage_data = {
            'input_tokens': 10000,
            'output_tokens': 6000,
            'total_tokens': total_used,
            'limit': limit,
            'remaining': limit - total_used,
            'usage_percent': (total_used / limit) * 100
        }

    context = {
        'usage_data': usage_data,
        'error': error
    }
    return render(request, 'general/billing.html', context)
