import os
from django.db.models import Sum

# Shared mock usage data (used when API key is missing or 'xxx') 
MOCK_USAGE = {
    'anthropic': {'input_tokens': 4000, 'output_tokens': 14500, 'total_tokens': 788, 'limit': 50000},
    'openai':    {'input_tokens': 1000, 'output_tokens': 10000, 'total_tokens': 55000, 'limit': 50000},
    'gemini':    {'input_tokens': 3000,  'output_tokens': 2000,  'total_tokens': 5000,  'limit': 50000},
}


def _has_real_api_key():
    """Check which API provider has a real key (not missing, not 'xxx')."""
    anthropic_key = os.environ.get('ANTHROPIC_API_KEY')
    openai_key = os.environ.get('OPENAI_API_KEY')
    gemini_key = os.environ.get('GEMINI_API_KEY')

    if anthropic_key and anthropic_key != 'xxx':
        return True, 'anthropic', 'Claude', 'https://console.anthropic.com/settings/billing'
    elif openai_key and openai_key != 'xxx':
        return True, 'openai', 'OpenAI', 'https://platform.openai.com/account/billing'
    elif gemini_key and gemini_key != 'xxx':
        return True, 'gemini', 'Gemini', 'https://aistudio.google.com/app/billing'
    else:
        return False, 'anthropic', 'Claude (Mock)', 'https://console.anthropic.com/settings/billing'


def _get_total_used_from_db(user):
    """Query all 4 models to get actual total token usage from DB."""
    from technical_seo.models import TechnicalSEOAudit
    from pricing_pr_monitor.models import PricingPRRun
    from keyword_research.models import KeywordResearchRun
    from content_gap.models import ContentGapAnalysis

    total_used = 0
    for model in [TechnicalSEOAudit, PricingPRRun, KeywordResearchRun, ContentGapAnalysis]:
        agg = model.objects.filter(
            requested_by=user
        ).aggregate(sum_tot=Sum('ai_total_tokens'))
        total_used += agg['sum_tot'] or 0
    return total_used


PROVIDER_DISPLAY = {
    'anthropic': {'name': 'Claude (Mock)', 'url': 'https://console.anthropic.com/settings/billing'},
    'openai':    {'name': 'OpenAI (Mock)', 'url': 'https://platform.openai.com/account/billing'},
    'gemini':    {'name': 'Gemini (Mock)', 'url': 'https://aistudio.google.com/app/billing'},
}


def api_status(request):
    """
    Context processor to provide AI API usage status and dynamic upgrade URLs
    across all templates.

    - Real API key → queries DB for actual token usage
    - No key or 'xxx' → checks all mock providers for any that exceed limits
    Computes limit-exceeded on every request (no stale session).
    """
    if not hasattr(request, 'user') or not request.user.is_authenticated:
        return {
            'api_provider': '',
            'api_upgrade_url': '#',
            'global_limit_exceeded': False,
        }

    has_real_key, _, api_provider, upgrade_url = _has_real_api_key()

    limit_exceeded = False

    try:
        if has_real_key:
            limit = int(os.environ.get('MONTHLY_TOKEN_LIMIT', 50000))
            total_used = _get_total_used_from_db(request.user)
            if limit > 0 and total_used >= limit:
                limit_exceeded = True
        else:
            # Mock mode: check ALL providers — alert for the first one that exceeds
            for api_key, mock in MOCK_USAGE.items():
                total_used = mock['total_tokens']
                limit = mock['limit']
                if limit > 0 and total_used >= limit:
                    limit_exceeded = True
                    display = PROVIDER_DISPLAY.get(api_key, PROVIDER_DISPLAY['anthropic'])
                    api_provider = display['name']
                    upgrade_url = display['url']
                    break
    except Exception:
        limit_exceeded = False

    return {
        'api_provider': api_provider,
        'api_upgrade_url': upgrade_url,
        'global_limit_exceeded': limit_exceeded,
    }
