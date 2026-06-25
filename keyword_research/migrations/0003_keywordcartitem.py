from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('keyword_research', '0002_keywordresearchproject_seed_keywords_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='KeywordCartItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('keyword', models.CharField(max_length=255)),
                ('source', models.CharField(blank=True, choices=[('ai', 'AI Keyword Ideas'), ('google', 'Google Keyword Planner')], max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('run', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='cart_items', to='keyword_research.keywordresearchrun')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='keyword_cart_items', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['keyword'],
            },
        ),
        migrations.AddIndex(
            model_name='keywordcartitem',
            index=models.Index(fields=['run', 'user'], name='keyword_res_run_id_7d4d6b_idx'),
        ),
        migrations.AddIndex(
            model_name='keywordcartitem',
            index=models.Index(fields=['keyword'], name='keyword_res_keyword_0f783b_idx'),
        ),
        migrations.AddConstraint(
            model_name='keywordcartitem',
            constraint=models.UniqueConstraint(fields=('run', 'user', 'keyword'), name='unique_keyword_cart_item'),
        ),
    ]
