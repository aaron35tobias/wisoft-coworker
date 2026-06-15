from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .models import Website


@login_required(login_url='sign-in')
def list_view(request):
    websites = Website.objects.filter(added_by=request.user)

    return render(request, 'page_speed_and_cwv/list.html', {
        'websites': websites,
    })
