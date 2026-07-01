from django.contrib import admin

from .models import (
    KeywordCartItem,
    KeywordCluster,
    KeywordIdea,
    KeywordPlannerMetric,
    KeywordResearchPage,
    KeywordResearchProject,
    KeywordResearchRun,
)


@admin.register(KeywordResearchProject)
class KeywordResearchProjectAdmin(admin.ModelAdmin):
    list_display = ('website_url', 'target_location', 'seed_topic', 'added_by', 'created_at')
    search_fields = ('website_url', 'target_location', 'seed_topic', 'added_by__username', 'added_by__email')


@admin.register(KeywordResearchRun)
class KeywordResearchRunAdmin(admin.ModelAdmin):
    list_display = ('project', 'status', 'pages_crawled', 'planner_status', 'started_at')
    list_filter = ('status', 'planner_status', 'started_at')
    search_fields = ('project__website_url', 'project__target_location')


@admin.register(KeywordResearchPage)
class KeywordResearchPageAdmin(admin.ModelAdmin):
    list_display = ('run', 'url', 'word_count', 'crawled_at')
    search_fields = ('url', 'title')


@admin.register(KeywordIdea)
class KeywordIdeaAdmin(admin.ModelAdmin):
    list_display = ('keyword', 'intent', 'funnel_stage', 'priority', 'run')
    search_fields = ('keyword', 'intent', 'suggested_page')
    list_filter = ('intent', 'funnel_stage', 'priority')


@admin.register(KeywordCluster)
class KeywordClusterAdmin(admin.ModelAdmin):
    list_display = ('cluster_name', 'intent', 'recommended_page_type', 'run')
    search_fields = ('cluster_name', 'intent')


@admin.register(KeywordPlannerMetric)
class KeywordPlannerMetricAdmin(admin.ModelAdmin):
    list_display = ('keyword', 'avg_monthly_searches', 'competition', 'run')
    search_fields = ('keyword',)


@admin.register(KeywordCartItem)
class KeywordCartItemAdmin(admin.ModelAdmin):
    list_display = ('keyword', 'source', 'run', 'user', 'created_at')
    list_filter = ('source', 'created_at')
    search_fields = ('keyword', 'user__username', 'user__email')
