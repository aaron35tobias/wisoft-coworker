from .models import Role


def role_permissions(request):
    role = None
    if request.user.is_authenticated:
        profile = getattr(request.user, 'profile', None)
        if profile:
            role = Role.objects.filter(name=profile.role).first()
    return {
        'current_role_permissions': role,
    }
