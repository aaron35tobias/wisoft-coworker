from celery import shared_task

from .analyzer import run_content_gap_analysis
from .models import ContentGapAnalysis


@shared_task(name='content_gap.run_analysis')
def run_content_gap_analysis_task(analysis_id):
    analysis = ContentGapAnalysis.objects.select_related('project', 'requested_by').get(id=analysis_id)
    run_content_gap_analysis(analysis)
