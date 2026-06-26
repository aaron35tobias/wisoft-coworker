import os
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.core.mail import send_mail
from django.conf import settings
import anthropic

from technical_seo.models import TechnicalSEOAudit
from page_speed_and_cwv.models import WebsiteSpeedReport, Website
from pricing_pr_monitor.models import PricingPRRun
from content_gap.models import ContentGapAnalysis


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
    """Most recent Page Speed website + a summary of its latest scan.

    Mirrors the Reports table: scanned-at, mobile/desktop performance score,
    and which devices were scanned.
    """
    website = (
        Website.objects
        .filter(added_by=user, is_active=True)
        .order_by('-date_added')
        .first()
    )
    if not website:
        return None

    scan = (
        website.speed_report_ai_indexes
        .prefetch_related('reports')
        .first()  # ordered by -scanned_at
    )

    data = {
        'domain': _domain(website.website_url),
        'has_report': scan is not None,
        'scanned_at': None,
        'mobile_score': None,
        'desktop_score': None,
        'devices': [],
    }
    if scan:
        reports = list(scan.reports.all())
        mobile = next((r for r in reports if r.device_type == WebsiteSpeedReport.DEVICE_MOBILE), None)
        desktop = next((r for r in reports if r.device_type == WebsiteSpeedReport.DEVICE_DESKTOP), None)
        devices = []
        if mobile:
            devices.append('Mobile')
        if desktop:
            devices.append('Desktop')
        data.update({
            'scanned_at': scan.scanned_at,
            'mobile_score': mobile.performance_score if mobile else None,
            'desktop_score': desktop.performance_score if desktop else None,
            'devices': devices,
        })
    return data


def _build_pricing(user):
    """Latest Pricing & PR monitor run for the most recently checked competitor."""
    run = (
        PricingPRRun.objects
        .filter(requested_by=user)
        .select_related('monitor')
        .order_by('-started_at')
        .first()
    )
    if not run:
        return None
    return {
        'competitor': run.monitor.competitor_name,
        'website': _domain(run.monitor.competitor_website),
        'status': run.get_status_display(),
        'runs': run.monitor.runs.count(),
        'changes': run.changes_found,
        'mentions': run.news_mentions_found,
        'started': run.started_at,
    }


def _build_content_gap(user):
    """Latest content gap analysis for the most recently analysed website."""
    analysis = (
        ContentGapAnalysis.objects
        .filter(requested_by=user)
        .select_related('project')
        .order_by('-started_at')
        .first()
    )
    if not analysis:
        return None

    priority_class = {'High': 'danger', 'Medium': 'warning', 'Low': 'success'}
    gaps = []
    for gap in (analysis.content_gaps or [])[:3]:
        priority = (gap.get('priority') or '').strip()
        gaps.append({
            'topic': gap.get('topic') or 'Content gap',
            'priority': priority or '—',
            'cls': priority_class.get(priority, 'secondary'),
        })

    url = analysis.own_url or (analysis.project.website_url if analysis.project else '')
    return {
        'website': _domain(url),
        'status': analysis.get_status_display(),
        'started': analysis.started_at,
        'gaps': gaps,
        'gaps_total': len(analysis.content_gaps or []),
        'keywords_total': len(analysis.keyword_opportunities or []),
    }


@login_required(login_url='sign-in')
def dashboard_view(request):
    context = {
        'tech': _build_technical_seo(request.user),
        'speed': _build_page_speed(request.user),
        'pricing': _build_pricing(request.user),
        'content_gap': _build_content_gap(request.user),
    }
    return render(request, 'general/dashboard.html', context)

from django.db.models import Sum
from technical_seo.models import TechnicalSEOAudit
from pricing_pr_monitor.models import PricingPRRun
from keyword_research.models import KeywordResearchRun
from content_gap.models import ContentGapAnalysis

@login_required(login_url='sign-in')
def billing_view(request):
    anthropic_key = os.environ.get('ANTHROPIC_API_KEY')
    openai_key = os.environ.get('OPENAI_API_KEY')
    gemini_key = os.environ.get('GEMINI_API_KEY')
    
    usage_data = None
    error = None
    limit_exceeded = False
    
    # Determine if any real API key is configured
    has_real_key = False
    if anthropic_key and anthropic_key != 'xxx':
        has_real_key = True
    elif openai_key and openai_key != 'xxx':
        has_real_key = True
    elif gemini_key and gemini_key != 'xxx':
        has_real_key = True

    if has_real_key:
        try:
            # Use environment variable for limit, default to 500k
            limit = int(os.environ.get('MONTHLY_TOKEN_LIMIT', 500000))
            
            total_input = 0
            total_output = 0
            total_used = 0
            
            # API providers (like Anthropic/OpenAI) don't have a standardized endpoint
            # for account-wide monthly token usage via the SDK.
            # Instead, we aggregate the usage locally tracked by our background jobs!
            models_to_check = [
                TechnicalSEOAudit,
                PricingPRRun,
                KeywordResearchRun,
                ContentGapAnalysis
            ]
            
            for model in models_to_check:
                # Aggregate tokens for the current user
                agg = model.objects.filter(requested_by=request.user).aggregate(
                    sum_in=Sum('ai_input_tokens'),
                    sum_out=Sum('ai_output_tokens'),
                    sum_tot=Sum('ai_total_tokens')
                )
                total_input += agg['sum_in'] or 0
                total_output += agg['sum_out'] or 0
                total_used += agg['sum_tot'] or 0
                
            usage_data = {
                'input_tokens': total_input,
                'output_tokens': total_output,
                'total_tokens': total_used,
                'limit': limit,
                'remaining': max(0, limit - total_used),
                'usage_percent': min((total_used / limit) * 100, 100) if limit > 0 else 100
            }
        except Exception as e:
            error = f"Error aggregating local token usage: {str(e)}"
    else:
        # Mock data if the keys are missing or 'xxx'
        limit = 50000
        total_used = 47688
        usage_data = {
            'input_tokens': 34000,
            'output_tokens': 14500,
            'total_tokens': total_used,
            'limit': limit,
            'remaining': max(0, limit - total_used),
            'usage_percent': min((total_used / limit) * 100, 100)
        }

    if usage_data:
        if usage_data['usage_percent'] >= 100:
            limit_exceeded = True
            request.session['limit_exceeded'] = True
            
            # Send email alert if not already sent in this session
            if not request.session.get('billing_alert_sent', False):
                user_email = request.user.email
                if user_email:
                    subject = 'Action Required: AI API Token Limit Exceeded'
                    message = f"Hello {request.user.username},\n\nYour AI API token usage has exceeded the monthly limit of {usage_data['limit']} tokens. Please upgrade your plan or check your usage details on the billing dashboard.\n\nThank you,\nWisoft Co-Worker"
                    try:
                        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [user_email])
                        request.session['billing_alert_sent'] = True
                    except Exception as e:
                        print(f"Failed to send email: {e}")

    context = {
        'usage_data': usage_data,
        'error': error,
        'limit_exceeded': limit_exceeded
    }
    return render(request, 'general/billing.html', context)
