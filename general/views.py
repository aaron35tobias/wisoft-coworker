import os
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
import anthropic

@login_required(login_url='sign-in')
def dashboard_view(request):
    return render(request, 'general/dashboard.html')

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
