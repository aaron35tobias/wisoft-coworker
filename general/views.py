import json
import os
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render, redirect
from django.core.mail import send_mail
from django.conf import settings
import anthropic

from technical_seo.models import TechnicalSEOAudit
from page_speed_and_cwv.models import WebsiteSpeedReport, Website
from pricing_pr_monitor.models import PricingPRRun
from content_gap.models import ContentGapAnalysis
from keyword_research.models import KeywordResearchRun, KeywordIdea
from bulk_alt_text.models import BulkAltTextAnalysis
from django.db.models import Sum, Q
from django.http import JsonResponse
from django.utils.safestring import mark_safe

from accounts.models import Profile, Role
from django.contrib.auth.models import User

def _domain(url):
    return url.split('://', 1)[-1].rstrip('/') if url else ''

def _build_technical_seo(user):
    audit = TechnicalSEOAudit.objects.filter(requested_by=user).select_related('website').order_by('-started_at').first()
    if not audit: return None
    score = max(0, 100 - audit.critical_issues * 20 - audit.high_issues * 8 - audit.medium_issues * 3 - audit.low_issues * 1)
    if score >= 80: label, color = 'Good', '#50CD89'
    elif score >= 50: label, color = 'Fair', '#FFC700'
    else: label, color = 'Poor', '#F1416C'
    return {'audit_id': audit.id, 'domain': _domain(audit.website.website_url), 'status': audit.get_status_display(), 'pages': audit.pages_crawled, 'issues': audit.issues_found, 'critical': audit.critical_issues, 'high': audit.high_issues, 'started': audit.started_at, 'health_score': score, 'health_label': label, 'health_color': color}

def _build_page_speed(user):
    website = Website.objects.filter(added_by=user, is_active=True).order_by('-date_added').first()
    if not website: return None
    scan = website.speed_report_ai_indexes.prefetch_related('reports').first()
    data = {'domain': _domain(website.website_url), 'has_report': scan is not None, 'scanned_at': None, 'mobile_score': None, 'desktop_score': None, 'devices': []}
    if scan:
        reports = list(scan.reports.all())
        mobile = next((r for r in reports if r.device_type == WebsiteSpeedReport.DEVICE_MOBILE), None)
        desktop = next((r for r in reports if r.device_type == WebsiteSpeedReport.DEVICE_DESKTOP), None)
        devices = []
        if mobile: devices.append('Mobile')
        if desktop: devices.append('Desktop')
        data.update({'scanned_at': scan.scanned_at, 'mobile_score': mobile.performance_score if mobile else None, 'desktop_score': desktop.performance_score if desktop else None, 'devices': devices})
    return data

def _build_pricing(user):
    run = PricingPRRun.objects.filter(requested_by=user).select_related('monitor').order_by('-started_at').first()
    if not run: return None
    return {'competitor': run.monitor.competitor_name, 'website': _domain(run.monitor.competitor_website), 'status': run.get_status_display(), 'runs': run.monitor.runs.count(), 'changes': run.changes_found, 'mentions': run.news_mentions_found, 'started': run.started_at}

def _build_content_gap(user):
    analysis = ContentGapAnalysis.objects.filter(requested_by=user).select_related('project').order_by('-started_at').first()
    if not analysis: return None
    priority_class = {'High': 'danger', 'Medium': 'warning', 'Low': 'success'}
    gaps = []
    for gap in (analysis.content_gaps or [])[:3]:
        priority = (gap.get('priority') or '').strip()
        gaps.append({'topic': gap.get('topic') or 'Content gap', 'priority': priority or '—', 'cls': priority_class.get(priority, 'secondary')})
    url = analysis.own_url or (analysis.project.website_url if analysis.project else '')
    return {'website': _domain(url), 'status': analysis.get_status_display(), 'started': analysis.started_at, 'gaps': gaps, 'gaps_total': len(analysis.content_gaps or []), 'keywords_total': len(analysis.keyword_opportunities or [])}

def _build_keyword(user):
    run = KeywordResearchRun.objects.filter(requested_by=user).select_related('project').order_by('-started_at').first()
    if not run: return None
    priority_class = {'High': 'danger', 'Medium': 'warning', 'Low': 'success'}
    ideas = []
    for idea in KeywordIdea.objects.filter(run=run)[:3]:
        priority = (idea.priority or '').strip()
        ideas.append({'keyword': idea.keyword, 'intent': idea.intent or '—', 'priority': priority or '—', 'cls': priority_class.get(priority, 'secondary')})
    return {'website': _domain(run.project.website_url), 'seed': run.project.seed_topic, 'status': run.get_status_display(), 'started': run.started_at, 'ideas': ideas, 'ideas_total': KeywordIdea.objects.filter(run=run).count()}

def _build_bulk_alt_text(user):
    analysis = BulkAltTextAnalysis.objects.filter(requested_by=user).order_by('-started_at').first()
    if not analysis: return None
    return {'website': _domain(analysis.page_url), 'page_title': analysis.page_title, 'status': analysis.get_status_display(), 'started': analysis.started_at, 'total_images': analysis.total_images, 'missing_alt': analysis.missing_alt_count, 'generated_alt': analysis.generated_alt_count}

@login_required(login_url='sign-in')
def dashboard_view(request):
    context = {
        'tech': _build_technical_seo(request.user),
        'speed': _build_page_speed(request.user),
        'pricing': _build_pricing(request.user),
        'content_gap': _build_content_gap(request.user),
        'keyword': _build_keyword(request.user),
        'bulk_alt_text': _build_bulk_alt_text(request.user),
    }
    return render(request, 'general/dashboard.html', context)

@login_required(login_url='sign-in')
def billing_view(request):
    selected_api = request.GET.get('api', 'anthropic')
    
    anthropic_key = os.environ.get('ANTHROPIC_API_KEY')
    openai_key = os.environ.get('OPENAI_API_KEY')
    gemini_key = os.environ.get('GEMINI_API_KEY')
    
    usage_data = None
    error = None
    limit_exceeded = False
    
    has_real_key = False
    api_provider = "Mock Data"
    api_upgrade_url = "#"
    model_filter = Q()

    if selected_api == 'anthropic' and anthropic_key and anthropic_key != 'xxx': 
        has_real_key = True
        api_provider = "Anthropic"
        api_upgrade_url = "https://console.anthropic.com/settings/billing"
        model_filter = Q(ai_model__icontains='claude') | Q(ai_model__icontains='anthropic')
    elif selected_api == 'openai' and openai_key and openai_key != 'xxx': 
        has_real_key = True
        api_provider = "OpenAI"
        api_upgrade_url = "https://platform.openai.com/account/billing"
        model_filter = Q(ai_model__icontains='gpt') | Q(ai_model__icontains='openai')
    elif selected_api == 'gemini' and gemini_key and gemini_key != 'xxx': 
        has_real_key = True
        api_provider = "Google Gemini"
        api_upgrade_url = "https://aistudio.google.com/app/billing"
        model_filter = Q(ai_model__icontains='gemini')
    else:
        # Fallback to mock data names if no key
        if selected_api == 'anthropic': api_provider = "Claude (Mock)"
        elif selected_api == 'openai': api_provider = "GPT (Mock)"
        elif selected_api == 'gemini': api_provider = "Gemini (Mock)"

    if has_real_key:
        try:
            limit = int(os.environ.get('MONTHLY_TOKEN_LIMIT', 50000)) #if key is real limit is 5K
            total_input = 0
            total_output = 0
            total_used = 0
            models_to_check = [TechnicalSEOAudit, PricingPRRun, KeywordResearchRun, ContentGapAnalysis]
            
            for model in models_to_check:
                agg = model.objects.filter(requested_by=request.user).filter(model_filter).aggregate(sum_in=Sum('ai_input_tokens'), sum_out=Sum('ai_output_tokens'), sum_tot=Sum('ai_total_tokens'))
                total_input += agg['sum_in'] or 0
                total_output += agg['sum_out'] or 0
                total_used += agg['sum_tot'] or 0
                
            usage_data = {
                'input_tokens': total_input, 'output_tokens': total_output, 'total_tokens': total_used, 'limit': limit,
                'remaining': max(0, limit - total_used), 'usage_percent': min((total_used / limit) * 100, 100) if limit > 0 else 100
            }
        except Exception as e:
            error = f"Error aggregating local token usage: {str(e)}"
    else:
        limit = 50000
        if selected_api == 'anthropic':
            total_used = 47688
            usage_data = {
                'input_tokens': 34000, 'output_tokens': 14500, 'total_tokens': total_used, 'limit': limit,
                'remaining': max(0, limit - total_used), 'usage_percent': min((total_used / limit) * 100, 100)
            }
        elif selected_api == 'openai':
            total_used = 25000
            usage_data = {
                'input_tokens': 15000, 'output_tokens': 10000, 'total_tokens': total_used, 'limit': limit,
                'remaining': max(0, limit - total_used), 'usage_percent': min((total_used / limit) * 100, 100)
            }
        elif selected_api == 'gemini':
            total_used = 5000
            usage_data = {
                'input_tokens': 3000, 'output_tokens': 2000, 'total_tokens': total_used, 'limit': limit,
                'remaining': max(0, limit - total_used), 'usage_percent': min((total_used / limit) * 100, 100)
            }

    if usage_data:
        if usage_data['usage_percent'] >= 100:
            limit_exceeded = True
            request.session['limit_exceeded'] = True
            if not request.session.get('billing_alert_sent', False):
                user_email = request.user.email
                if user_email:
                    subject = 'Action Required: AI API Token Limit Exceeded'
                    message = f"Hello {request.user.username},\n\nYour AI API token usage has exceeded the monthly limit of {usage_data['limit']} tokens. Please upgrade your plan or check your usage details on the billing dashboard.\n\nThank you,\nWisoft Co-Worker"
                    try:
                        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [user_email])
                        request.session['billing_alert_sent'] = True
                    except Exception as e:
                        pass
        else:
            limit_exceeded = False
            request.session['limit_exceeded'] = False
            request.session['billing_alert_sent'] = False

    context = {
        'usage_data': usage_data, 
        'error': error, 
        'limit_exceeded': limit_exceeded,
        'api_provider': api_provider,
        'api_upgrade_url': api_upgrade_url,
        'selected_api': selected_api
    }
    return render(request, 'general/billing.html', context)

@login_required(login_url='sign-in')
def token_usage_chart_api(request):
    selected_api = request.GET.get('api', 'anthropic')
    
    anthropic_key = os.environ.get('ANTHROPIC_API_KEY')
    openai_key = os.environ.get('OPENAI_API_KEY')
    gemini_key = os.environ.get('GEMINI_API_KEY')
    
    has_real_key = False
    model_filter = Q()
    
    if selected_api == 'anthropic' and anthropic_key and anthropic_key != 'xxx': 
        has_real_key = True
        model_filter = Q(ai_model__icontains='claude') | Q(ai_model__icontains='anthropic')
    elif selected_api == 'openai' and openai_key and openai_key != 'xxx': 
        has_real_key = True
        model_filter = Q(ai_model__icontains='gpt') | Q(ai_model__icontains='openai')
    elif selected_api == 'gemini' and gemini_key and gemini_key != 'xxx': 
        has_real_key = True
        model_filter = Q(ai_model__icontains='gemini')
        
    if has_real_key:
        total_used = 0
        models_to_check = [TechnicalSEOAudit, PricingPRRun, KeywordResearchRun, ContentGapAnalysis]
        try:
            for model in models_to_check:
                agg = model.objects.filter(requested_by=request.user).filter(model_filter).aggregate(sum_tot=Sum('ai_total_tokens'))
                total_used += agg['sum_tot'] or 0
            data = {"categories": ["Week 1", "Week 2", "Week 3", "Current"], "series": [{"name": "API Tokens Used", "data": [int(total_used * 0.2), int(total_used * 0.5), int(total_used * 0.8), total_used]}]}
        except Exception:
            data = {"categories": ["Week 1", "Week 2", "Week 3", "Current"], "series": [{"name": "API Tokens Used", "data": [0, 0, 0, 0]}]}
    else:
        if selected_api == 'anthropic':
            data = {"categories": ["Week 1", "Week 2", "Week 3", "Current"], "series": [{"name": "API Tokens Used", "data": [10000, 25000, 40000, 57688]}]}
        elif selected_api == 'openai':
            data = {"categories": ["Week 1", "Week 2", "Week 3", "Current"], "series": [{"name": "API Tokens Used", "data": [5000, 12000, 18000, 25000]}]}
        elif selected_api == 'gemini':
            data = {"categories": ["Week 1", "Week 2", "Week 3", "Current"], "series": [{"name": "API Tokens Used", "data": [1000, 2000, 3000, 5000]}]}
        else:
            data = {"categories": ["Week 1", "Week 2", "Week 3", "Current"], "series": [{"name": "API Tokens Used", "data": [0, 0, 0, 0]}]}
    return JsonResponse(data)


@login_required(login_url='sign-in')
@user_passes_test(lambda u: u.is_superuser)
def roles_permissions_view(request):
    Role.ensure_defaults()

    permission_fields = [
        'seo_view', 'seo_page_speed_and_cwv', 'seo_pricing_pr_monitor', 'seo_brand_mentions',
        'seo_keyword_research', 'seo_technical_seo_audit', 'seo_serp_analysis', 'seo_internal_linking',
        'seo_content_gaps', 'seo_bulk_alt_text', 'analytics_view', 'analytics_overview',
        'analytics_traffic_insights', 'analytics_performance_trends', 'automation_view',
        'automation_ai_workflows', 'automation_prompt_library', 'automation_automation_rules',
    ]

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'create_role':
            role_name = (request.POST.get('new_role_name') or request.POST.get('role_name') or '').strip().lower()
            if role_name:
                role, _ = Role.objects.get_or_create(name=role_name)
                for field in permission_fields:
                    setattr(role, field, bool(request.POST.get(field)))
                role.save()

        elif action == 'save_role_permissions':
            role_name = request.POST.get('role_name', '').strip().lower()
            role = Role.objects.filter(name=role_name).first()
            if role:
                for field in permission_fields:
                    setattr(role, field, bool(request.POST.get(field)))
                role.save()

        elif action == 'create_user':
            username = request.POST.get('username', '').strip()
            email = request.POST.get('email', '').strip()
            password = request.POST.get('password', '')
            initial_role = request.POST.get('initial_role', '').strip().lower() or 'user'
            if username and password:
                user = User.objects.create_user(username=username, email=email, password=password)
                profile, _ = Profile.objects.get_or_create(user=user)
                profile.role = initial_role
                profile.save()

        elif action == 'assign_user_role':
            user = User.objects.filter(id=request.POST.get('assign_user_id')).first()
            assign_role_name = request.POST.get('assign_role_name', 'user').strip().lower() or 'user'
            if user:
                profile, _ = Profile.objects.get_or_create(user=user)
                profile.role = assign_role_name
                profile.save()

        elif action == 'remove_role_member':
            role_name = request.POST.get('role_name', '').strip().lower() or 'user'
            user = User.objects.filter(id=request.POST.get('user_id')).first()
            if user:
                profile, _ = Profile.objects.get_or_create(user=user)
                profile.role = 'user'
                profile.save()
                if request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest':
                    user_count = Profile.objects.filter(role=role_name).count()
                    return JsonResponse({'success': True, 'role_name': role_name, 'user_count': user_count})

        elif action == 'delete_user':
            user = User.objects.filter(id=request.POST.get('user_id')).first()
            if user and not user.is_superuser:
                user.delete()

        elif action == 'delete_role':
            role_name = request.POST.get('role_name', '').strip().lower()
            role = Role.objects.filter(name=role_name).first()
            if role:
                Profile.objects.filter(role=role_name).update(role='user')
                role.delete()

        return redirect('roles-permissions')

    users = []
    for user in User.objects.select_related('profile').all():
        role_name = getattr(getattr(user, 'profile', None), 'role', None) or ('admin' if user.is_superuser else 'user')
        users.append({
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'full_name': user.get_full_name(),
            'role': role_name,
            'is_active': user.is_active,
            'is_superuser': user.is_superuser,
        })

    role_counts = {}
    for user in users:
        role_counts[user['role']] = role_counts.get(user['role'], 0) + 1

    roles = list(Role.objects.all())
    for role in roles:
        role.user_count = role_counts.get(role.name, 0)

    role_user_data = {}
    for user in users:
        role_user_data.setdefault(user['role'], []).append({
            'id': user['id'],
            'username': user['username'],
            'full_name': user['full_name'],
            'email': user['email'],
        })

    return render(request, 'accounts/roles_permissions.html', {
        'users': users,
        'roles': roles,
        'role_user_data_json': mark_safe(json.dumps(role_user_data)),
    })
