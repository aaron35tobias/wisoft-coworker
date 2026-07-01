from celery import shared_task

from .models import TechnicalSEOAudit
from .seo_audit import run_technical_seo_audit


@shared_task(name='technical_seo.run_audit')
def run_technical_seo_audit_task(audit_id):
    audit = TechnicalSEOAudit.objects.select_related('website', 'requested_by').get(id=audit_id)
    run_technical_seo_audit(audit)
