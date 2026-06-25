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
    return render(request, 'accounts/profile.html', {'user': user})


@login_required(login_url='sign-in')
def settings_view(request):
    user = request.user
    if request.method == 'POST':
        action = request.POST.get('action')
        errors = {}
        success_message = ''
        
        if action == 'update_username':
            new_username = request.POST.get('username', '').strip()
            
            if not new_username:
                errors['username'] = 'Username is required.'
            elif new_username == user.username:
                errors['username'] = 'New username must be different from your current username.'
            elif User.objects.filter(username=new_username).exists():
                errors['username'] = 'Username is already taken.'
                
            if not errors:
                user.username = new_username
                user.save()
                success_message = 'Username updated successfully.'
                
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
                update_session_auth_hash(request, user)  # Keep user logged in
                success_message = 'Password updated successfully.'
                
        elif action == 'update_profile_picture':
            profile_picture = request.FILES.get('profile_picture')
            if profile_picture:
                user.profile.profile_picture = profile_picture
                user.profile.save()
                success_message = 'Profile picture updated successfully.'
            else:
                errors['profile_picture'] = 'Please select an image to upload.'
                
        context = {
            'errors': errors,
            'success_message': success_message,
        }
        return render(request, 'accounts/settings.html', context)
        
    return render(request, 'accounts/settings.html')
