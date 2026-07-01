from django.contrib.auth import authenticate, get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

User = get_user_model()

def sign_in_view(request):
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        errors = {}

        if not username:
            errors['username'] = 'Username is required.'

        if not password:
            errors['password'] = 'Password is required.'

        if not errors:
            user = authenticate(
                request,
                username=username,
                password=password,
            )

            if user is not None:
                login(request, user)
                return redirect('dashboard')

            pending_user = User.objects.filter(username=username).first()

            if (
                pending_user is not None
                and not pending_user.is_active
                and pending_user.check_password(password)
            ):
                errors['login'] = (
                    'Your account is waiting for administrator approval.'
                )
            else:
                errors['login'] = 'Invalid username or password.'

        context = {
            'errors': errors,
            'username': username,
        }
        return render(request, 'accounts/sign-in.html', context)

    return render(request, 'accounts/sign-in.html')


def sign_up_view(request):
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password1 = request.POST.get('password1', '')
        password2 = request.POST.get('password2', '')
        errors = {}

        if not username:
            errors['username'] = 'Username is required.'

        if not email:
            errors['email'] = 'Email is required.'

        if not password1:
            errors['password1'] = 'Password is required.'

        if not password2:
            errors['password2'] = 'Confirm password is required.'

        if password1 and password2 and password1 != password2:
            errors['password2'] = 'Passwords do not match.'

        if username and User.objects.filter(username=username).exists():
            errors['username'] = 'Username already exists.'

        if email and User.objects.filter(email=email).exists():
            errors['email'] = 'Email already exists.'

        if not errors:
            User.objects.create_user(
                username=username,
                email=email,
                password=password1,
                is_active=False,
            )
            return redirect('sign-in')

        context = {
            'errors': errors,
            'username': username,
            'email': email,
        }
        return render(request, 'accounts/sign-up.html', context)
    return render(request, 'accounts/sign-up.html')


@require_POST
@login_required(login_url='sign-in')
def logout_view(request):
    logout(request)
    return redirect('sign-in')


@login_required(login_url='sign-in')
def profile_view(request):
    user = request.user
    errors = {}
    success_message = ''
    active_section = request.GET.get('section', 'personal_info')

    profile_strength = 20
    if user.email:
        profile_strength += 20
    if user.first_name or user.last_name:
        profile_strength += 20
    if hasattr(user, 'profile') and user.profile.profile_picture:
        profile_strength += 20
    if hasattr(user, 'profile') and user.profile.banner_image:
        profile_strength += 20

    profile_strength_offset = max(0, min(257.6, 257.6 - (profile_strength * 2.576)))

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'update_banner_image':
            banner_image = request.FILES.get('banner_image')
            if banner_image:
                user.profile.banner_image = banner_image
                user.profile.save()
                success_message = 'Banner image updated successfully.'
            else:
                errors['banner_image'] = 'Please select an image to upload.'
            active_section = 'banner'

        elif action == 'update_profile_picture':
            profile_picture = request.FILES.get('profile_picture')
            if profile_picture:
                user.profile.profile_picture = profile_picture
                user.profile.save()
                success_message = 'Profile picture updated successfully.'
            else:
                errors['profile_picture'] = 'Please select an image to upload.'
            active_section = 'profile_picture'

        elif action == 'update_profile_details':
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()
            new_username = request.POST.get('username', '').strip()

            if not new_username:
                errors['username'] = 'Username is required.'
            elif User.objects.filter(username=new_username).exclude(pk=user.pk).exists():
                errors['username'] = 'Username is already taken.'

            if not errors:
                user.first_name = first_name
                user.last_name = last_name
                user.username = new_username
                user.save()
                success_message = 'Profile details updated successfully.'
            
            # If there are errors in the form submission, we set active_section 
            # to 'profile_edit' so the template can keep the form open on page reload
            if errors:
                active_section = 'profile_edit'
            else:
                active_section = 'personal_info'

        elif action == 'update_password':
            current_password = request.POST.get('current_password', '')
            new_password = request.POST.get('new_password', '')
            confirm_password = request.POST.get('confirm_password', '')

            if not current_password:
                errors['password_current_password'] = 'Current password is required.'
            elif not user.check_password(current_password):
                errors['password_current_password'] = 'Incorrect current password.'

            if not new_password:
                errors['new_password'] = 'New password is required.'
            elif len(new_password) < 8:
                errors['new_password'] = 'Password must be at least 8 characters long.'

            if new_password != confirm_password:
                errors['confirm_password'] = 'Passwords do not match.'

            if not errors:
                user.set_password(new_password)
                user.save()
                update_session_auth_hash(request, user)
                success_message = 'Password updated successfully.'
            active_section = 'password'

        context = {
            'errors': errors,
            'success_message': success_message,
            'active_section': active_section,
            'profile_strength': profile_strength,
            'profile_strength_offset': profile_strength_offset,
        }
        return render(request, 'accounts/profile.html', context)

    context = {
        'active_section': active_section,
        'profile_strength': profile_strength,
        'profile_strength_offset': profile_strength_offset,
    }
    return render(request, 'accounts/profile.html', context)


@login_required(login_url='sign-in')
def settings_view(request):
    return redirect('profile')
