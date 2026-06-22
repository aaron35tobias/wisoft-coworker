from django.contrib.auth import authenticate, get_user_model, login, logout
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
