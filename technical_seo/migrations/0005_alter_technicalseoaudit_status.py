from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('technical_seo', '0004_technicalseoaudit_pagespeed_desktop_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='technicalseoaudit',
            name='status',
            field=models.CharField(
                choices=[
                    ('running', 'Running'),
                    ('crawl_completed', 'Crawl Completed'),
                    ('completed', 'Completed'),
                    ('failed', 'Failed'),
                ],
                default='running',
                max_length=20,
            ),
        ),
    ]
