from django.contrib.auth import authenticate, get_user_model, login
from django.shortcuts import redirect, render


User = get_user_model()


def login_view(request):
    if request.method == 'GET':
        return render(request, 'pages/login.html')

    username = request.POST.get('username', '').strip()
    password = request.POST.get('password', '')
    errors = {}

    if not username:
        errors['username'] = 'Username is required.'

    if not password:
        errors['password'] = 'Password is required.'

    if errors:
        return render(request, 'pages/login.html', {
            'errors': errors,
            'username': username,
        })

    user = authenticate(request, username=username, password=password)

    if user is None:
        return render(request, 'pages/login.html', {
            'errors': {'login': 'Invalid username or password.'},
            'username': username,
        })

    login(request, user)
    return redirect('dashboard')


def signup_view(request):
    if request.method == 'GET':
        return render(request, 'pages/signup.html')

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

    if errors:
        return render(request, 'pages/signup.html', {
            'errors': errors,
            'username': username,
            'email': email,
        })

    user = User.objects.create_user(
        username=username,
        email=email,
        password=password1,
    )
    login(request, user)
    return redirect('dashboard')
