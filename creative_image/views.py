from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required(login_url='sign-in')
def image_variations_view(request):
    # Frontend only. The backend team will add POST handling here to run the
    # image generation and return the left/right side-view images.
    return render(request, 'creative_image/image_variations.html')
