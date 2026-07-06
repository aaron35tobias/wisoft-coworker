from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0009_role_profile_role'),
    ]

    operations = [
        migrations.AddField(
            model_name='role',
            name='seo_page_speed_and_cwv',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='role',
            name='seo_pricing_pr_monitor',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='role',
            name='seo_brand_mentions',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='role',
            name='seo_keyword_research',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='role',
            name='seo_technical_seo_audit',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='role',
            name='seo_serp_analysis',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='role',
            name='seo_internal_linking',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='role',
            name='seo_content_gaps',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='role',
            name='seo_bulk_alt_text',
            field=models.BooleanField(default=True),
        ),
        migrations.RemoveField(
            model_name='role',
            name='seo_overview',
        ),
        migrations.RemoveField(
            model_name='role',
            name='seo_traffic_insights',
        ),
        migrations.RemoveField(
            model_name='role',
            name='seo_performance_trends',
        ),
    ]
