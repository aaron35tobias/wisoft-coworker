import os

from celery import Celery


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wisoft_co_worker.settings')

app = Celery('wisoft_co_worker')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
