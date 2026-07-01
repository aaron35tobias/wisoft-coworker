from django.db import models
from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

User = get_user_model()


class Role(models.Model):
    name = models.CharField(max_length=32, unique=True)
    seo_view = models.BooleanField(default=True)
    seo_page_speed_and_cwv = models.BooleanField(default=True)
    seo_pricing_pr_monitor = models.BooleanField(default=True)
    seo_brand_mentions = models.BooleanField(default=True)
    seo_keyword_research = models.BooleanField(default=True)
    seo_technical_seo_audit = models.BooleanField(default=True)
    seo_serp_analysis = models.BooleanField(default=True)
    seo_internal_linking = models.BooleanField(default=True)
    seo_content_gaps = models.BooleanField(default=True)
    seo_bulk_alt_text = models.BooleanField(default=True)
    analytics_view = models.BooleanField(default=True)
    analytics_overview = models.BooleanField(default=True)
    analytics_traffic_insights = models.BooleanField(default=True)
    analytics_performance_trends = models.BooleanField(default=True)
    automation_view = models.BooleanField(default=True)
    automation_ai_workflows = models.BooleanField(default=True)
    automation_prompt_library = models.BooleanField(default=True)
    automation_automation_rules = models.BooleanField(default=True)

    def __str__(self):
        return self.name.title()

    def has_permission(self, permission_name):
        return getattr(self, permission_name, False)

    @classmethod
    def ensure_defaults(cls):
        default_roles = [
            {
                'name': 'admin',
                'seo_view': True,
                'seo_page_speed_and_cwv': True,
                'seo_pricing_pr_monitor': True,
                'seo_brand_mentions': True,
                'seo_keyword_research': True,
                'seo_technical_seo_audit': True,
                'seo_serp_analysis': True,
                'seo_internal_linking': True,
                'seo_content_gaps': True,
                'seo_bulk_alt_text': True,
                'analytics_view': True,
                'analytics_overview': True,
                'analytics_traffic_insights': True,
                'analytics_performance_trends': True,
                'automation_view': True,
                'automation_ai_workflows': True,
                'automation_prompt_library': True,
                'automation_automation_rules': True,
            },
            {
                'name': 'manager',
                'seo_view': True,
                'seo_page_speed_and_cwv': True,
                'seo_pricing_pr_monitor': True,
                'seo_brand_mentions': True,
                'seo_keyword_research': True,
                'seo_technical_seo_audit': True,
                'seo_serp_analysis': True,
                'seo_internal_linking': True,
                'seo_content_gaps': True,
                'seo_bulk_alt_text': True,
                'analytics_view': True,
                'analytics_overview': True,
                'analytics_traffic_insights': True,
                'analytics_performance_trends': True,
                'automation_view': False,
                'automation_ai_workflows': False,
                'automation_prompt_library': False,
                'automation_automation_rules': False,
            },
            {
                'name': 'user',
                'seo_view': True,
                'seo_page_speed_and_cwv': True,
                'seo_pricing_pr_monitor': False,
                'seo_brand_mentions': False,
                'seo_keyword_research': False,
                'seo_technical_seo_audit': False,
                'seo_serp_analysis': False,
                'seo_internal_linking': False,
                'seo_content_gaps': False,
                'seo_bulk_alt_text': False,
                'analytics_view': False,
                'analytics_overview': False,
                'analytics_traffic_insights': False,
                'analytics_performance_trends': False,
                'automation_view': False,
                'automation_ai_workflows': False,
                'automation_prompt_library': False,
                'automation_automation_rules': False,
            },
        ]

        for role_data in default_roles:
            cls.objects.get_or_create(name=role_data['name'], defaults=role_data)


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    profile_picture = models.ImageField(upload_to='profile_pics/', blank=True, null=True)
    banner_image = models.ImageField(upload_to='profile_banners/', blank=True, null=True)
    role = models.CharField(max_length=32, default='user')

    def __str__(self):
        return f"{self.user.username}'s Profile"


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance, role=('admin' if instance.is_superuser else 'user'))


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    if not hasattr(instance, 'profile'):
        Profile.objects.create(user=instance, role=('admin' if instance.is_superuser else 'user'))
    if instance.is_superuser and instance.profile.role != 'admin':
        instance.profile.role = 'admin'
    instance.profile.save()
