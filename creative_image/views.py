import json
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt
from .models import ImageVariationJob
from .tasks import process_image_variation

@login_required(login_url='sign-in')
def image_variations_view(request):
    """Renders the frontend page"""
    return render(request, 'creative_image/image_variations.html')

# We can make this @login_required later, using @csrf_exempt for easy API testing if needed,
# but it's best to keep it secure. Since it's used from the frontend, CSRF token should be passed.
@login_required(login_url='sign-in')
@require_POST
def api_generate(request):
    """Receives the image upload and triggers the Celery task."""
    if 'image' not in request.FILES:
        return JsonResponse({'error': 'No image provided.'}, status=400)
        
    uploaded_file = request.FILES['image']
    
    # We expect perspectives as a comma-separated string or multiple form fields
    perspectives_raw = request.POST.get('perspectives', '')
    perspectives = [p.strip() for p in perspectives_raw.split(',') if p.strip()]
    if not perspectives:
        perspectives = ['Front view'] # Default fallback
    
    # Basic validation
    if uploaded_file.size > 10 * 1024 * 1024:
        return JsonResponse({'error': 'File too large. Max 10MB.'}, status=400)
        
    if not uploaded_file.name.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
        return JsonResponse({'error': 'Unsupported file format. Use PNG, JPG, or WEBP.'}, status=400)

    # Create job
    job = ImageVariationJob.objects.create(original_image=uploaded_file)
    
    # Trigger celery task with perspectives
    process_image_variation.delay(str(job.id), perspectives)
    
    return JsonResponse({
        'message': 'Job started successfully',
        'job_id': str(job.id),
        'status': job.status
    })

@login_required(login_url='sign-in')
@require_GET
def api_status(request, job_id):
    """Returns the current status of the job and image URLs if completed."""
    try:
        job = ImageVariationJob.objects.get(id=job_id)
        
        variations = []
        for var in job.variations.all():
            variations.append({
                'name': var.name,
                'url': var.image.url if var.image else None
            })
            
        response_data = {
            'job_id': str(job.id),
            'status': job.status,
            'variations': variations,
            'error': job.error_message
        }
        return JsonResponse(response_data)
    except ImageVariationJob.DoesNotExist:
        return JsonResponse({'error': 'Job not found.'}, status=404)
