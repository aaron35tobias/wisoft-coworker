from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('technical_seo', '0001_initial'),
        ('page_speed_and_cwv', '0007_technicalseowebsite_alter_technicalseoaudit_website_and_more'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.DeleteModel(name='TechnicalSEOIssue'),
                migrations.DeleteModel(name='TechnicalSEOPage'),
                migrations.DeleteModel(name='TechnicalSEOAudit'),
                migrations.DeleteModel(name='TechnicalSEOWebsite'),
            ],
        ),
    ]
