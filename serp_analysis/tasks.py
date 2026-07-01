from celery import shared_task

from .analyzer import run_serp_analysis
from .models import SERPAnalysis


@shared_task(name='serp_analysis.run_analysis')
def run_serp_analysis_task(analysis_id):
    analysis = SERPAnalysis.objects.select_related('requested_by').get(id=analysis_id)
    run_serp_analysis(analysis)
