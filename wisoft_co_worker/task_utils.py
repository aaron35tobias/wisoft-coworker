from django.utils import timezone


def enqueue_background_task(task, record, failure_prefix):
    try:
        task.delay(record.id)
        return True
    except Exception as exc:
        record.status = record.STATUS_FAILED
        record.error_message = f'{failure_prefix}: {exc}'
        record.completed_at = timezone.now()
        record.save(update_fields=['status', 'error_message', 'completed_at'])
        return False
