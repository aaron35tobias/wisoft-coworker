from celery import shared_task

from .models import KeywordResearchRun
from .research import run_keyword_research


@shared_task(name='keyword_research.run_research')
def run_keyword_research_task(run_id):
    run = KeywordResearchRun.objects.select_related('project', 'requested_by').get(id=run_id)
    run_keyword_research(run)
