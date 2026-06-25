from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from .analyzer import normalize_page_url, run_bulk_alt_text_analysis
from .models import BulkAltTextAnalysis


@login_required(login_url='sign-in')
def generate_view(request):
    analyses = BulkAltTextAnalysis.objects.filter(requested_by=request.user)[:10]
    context = {
        'analyses': analyses,
    }
    return render(request, 'bulk_alt_text/generate.html', context)


@login_required(login_url='sign-in')
def history_view(request):
    analyses = BulkAltTextAnalysis.objects.filter(requested_by=request.user)
    context = {
        'analyses': analyses,
    }
    return render(request, 'bulk_alt_text/history.html', context)


@login_required(login_url='sign-in')
def run_view(request):
    if request.method != 'POST':
        return redirect('bulk_alt_text:generate')

    page_url = normalize_page_url(request.POST.get('page_url', '').strip())

    try:
        URLValidator()(page_url)
    except ValidationError:
        messages.error(request, 'Enter a valid page URL.')
        return redirect('bulk_alt_text:generate')

    analysis = BulkAltTextAnalysis.objects.create(page_url=page_url, requested_by=request.user)

    try:
        run_bulk_alt_text_analysis(analysis)
        analysis.status = BulkAltTextAnalysis.STATUS_COMPLETED
        analysis.completed_at = timezone.now()
        analysis.save()
        messages.success(request, 'Bulk alt text analysis completed successfully.')
    except Exception as error:
        analysis.status = BulkAltTextAnalysis.STATUS_FAILED
        analysis.error_message = str(error)
        analysis.completed_at = timezone.now()
        analysis.save()
        messages.error(request, f'Bulk alt text analysis failed: {error}')

    return redirect('bulk_alt_text:detail', analysis.id)


@login_required(login_url='sign-in')
def detail_view(request, analysis_id):
    analysis = get_object_or_404(BulkAltTextAnalysis, id=analysis_id, requested_by=request.user)
    context = {
        'analysis': analysis,
        'back_to_history_url': reverse('bulk_alt_text:history'),
    }
    return render(request, 'bulk_alt_text/detail.html', context)


@login_required(login_url='sign-in')
def delete_view(request, analysis_id):
    analysis = get_object_or_404(BulkAltTextAnalysis, id=analysis_id, requested_by=request.user)

    if request.method == 'POST':
        analysis.delete()
        messages.success(request, 'Record deleted successfully.')
        next_url = request.POST.get('next', '').strip()
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
            return redirect(next_url)
        return redirect('bulk_alt_text:history')

    return redirect('bulk_alt_text:history')
