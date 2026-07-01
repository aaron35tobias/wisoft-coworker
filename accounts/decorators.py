from functools import wraps
from django.core.exceptions import PermissionDenied
from accounts.models import Role

def role_required(permission_name):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return view_func(request, *args, **kwargs) # Let login_required handle redirect

            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)
            
            profile = getattr(request.user, 'profile', None)
            if profile:
                role = Role.objects.filter(name=profile.role).first()
                if role and getattr(role, permission_name, False):
                    return view_func(request, *args, **kwargs)
            
            raise PermissionDenied
        return _wrapped_view
    return decorator
