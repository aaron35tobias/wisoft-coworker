import os

def api_status(request):
    """
    Context processor to provide AI API usage status and dynamic upgrade URLs
    across all templates.
    """
    anthropic_key = os.environ.get('ANTHROPIC_API_KEY')
    openai_key = os.environ.get('OPENAI_API_KEY')
    gemini_key = os.environ.get('GEMINI_API_KEY')

    api_provider = 'Claude (Mock)'
    upgrade_url = 'https://console.anthropic.com/settings/billing'

    if anthropic_key and anthropic_key != 'xxx':
        api_provider = 'Claude'
        upgrade_url = 'https://console.anthropic.com/settings/billing'
    elif openai_key and openai_key != 'xxx':
        api_provider = 'OpenAI'
        upgrade_url = 'https://platform.openai.com/account/billing'
    elif gemini_key and gemini_key != 'xxx':
        api_provider = 'Gemini'
        upgrade_url = 'https://aistudio.google.com/app/billing'

    # Check session to see if limit exceeded has been triggered (by view logic)
    limit_exceeded = request.session.get('limit_exceeded', False)

    # For mock data, the hardcoded usage is 47,688 out of 50,000 (95%).
    # We rely on the session 'limit_exceeded' or actual threshold logic instead of forcing it to True.

    return {
        'api_provider': api_provider,
        'api_upgrade_url': upgrade_url,
        'global_limit_exceeded': limit_exceeded,
    }
