from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.shortcuts import get_object_or_404, redirect, render

from .models import Website


@login_required(login_url='sign-in')
def list_view(request):
    websites = Website.objects.filter(added_by=request.user)
    context = { 'websites': websites, }
    return render(request, 'page_speed_and_cwv/list.html', context)


@login_required(login_url='sign-in')
def create_view(request):
    if request.method == 'POST':
        website_url = request.POST.get('website_url', '').strip()
        note = request.POST.get('note', '').strip()

        if not website_url:
            messages.error(request, 'Website URL is required.')
            return redirect('page_speed_and_cwv:website-list')

        try:
            URLValidator()(website_url)
        except ValidationError:
            messages.error(request, 'Enter a valid website URL.')
            return redirect('page_speed_and_cwv:website-list')

        Website.objects.create(website_url=website_url,note=note,added_by=request.user,)

        messages.success(request, 'Website added successfully.')
        return redirect('page_speed_and_cwv:website-list')

    return redirect('page_speed_and_cwv:website-list')


@login_required(login_url='sign-in')
def update_view(request):
    if request.method == 'POST':
        website_id = request.POST.get('website_id')
        website_url = request.POST.get('website_url', '').strip()
        note = request.POST.get('note', '').strip()
        website = get_object_or_404(
            Website,
            id=website_id,
            added_by=request.user,
        )

        if not website_url:
            messages.error(request, 'Website URL is required.')
            return redirect('page_speed_and_cwv:website-list')

        try:
            URLValidator()(website_url)
        except ValidationError:
            messages.error(request, 'Enter a valid website URL.')
            return redirect('page_speed_and_cwv:website-list')

        website.website_url = website_url
        website.note = note
        website.save()

        messages.success(request, 'Website updated successfully.')
        return redirect('page_speed_and_cwv:website-list')

    return redirect('page_speed_and_cwv:website-list')


@login_required(login_url='sign-in')
def delete_view(request, website_id):
    website = get_object_or_404(
        Website,
        id=website_id,
        added_by=request.user,
    )

    if request.method == 'POST':
        website.delete()
        messages.success(request, 'Website deleted successfully.')
        return redirect('page_speed_and_cwv:website-list')

    return redirect('page_speed_and_cwv:website-list')
