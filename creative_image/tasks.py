import os
import uuid
import requests
import base64
from django.core.files.base import ContentFile
from celery import shared_task
from django.conf import settings
from .models import ImageVariationJob, GeneratedVariation
import logging

logger = logging.getLogger(__name__)

@shared_task
def process_image_variation(job_id, perspectives=None):
    if perspectives is None:
        perspectives = ['Front view']
        
    try:
        job = ImageVariationJob.objects.get(id=job_id)
        job.status = 'PROCESSING'
        job.save()

        api_key = os.environ.get('AI_IMAGE_API_KEY')
        
        if not api_key:
            logger.error("AI_IMAGE_API_KEY not found in environment.")
            job.status = 'FAILED'
            job.error_message = 'AI API Key is missing. Please configure AI_IMAGE_API_KEY.'
            job.save()
            return
            
        # Read image bytes
        job.original_image.seek(0)
        image_bytes = job.original_image.read()
        image_b64 = base64.b64encode(image_bytes).decode('utf-8')
        
        headers = {"Content-Type": "application/json"}
        
        # ---- STEP 1: Use Gemini 2.5 Flash (text model, has free quota) to describe the image ----
        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        
        describe_data = {
            "contents": [{
                "parts": [
                    {"inline_data": {
                        "mime_type": "image/jpeg",
                        "data": image_b64
                    }},
                    {"text": (
                        "Describe the main subject of this image in one short sentence for an image generator. "
                        "Include only key visual features. Max 30 words."
                    )}
                ]
            }]
        }
        
        logger.info(f"Step 1: Asking Gemini 2.5 Flash to describe the subject for job {job_id}...")
        desc_res = requests.post(gemini_url, headers=headers, json=describe_data)
        if desc_res.status_code != 200:
            raise Exception(f"Gemini Text API Error ({desc_res.status_code}): {desc_res.text}")
            
        desc_json = desc_res.json()
        try:
            subject_description = desc_json['candidates'][0]['content']['parts'][0]['text']
        except (KeyError, IndexError):
            raise Exception("Failed to parse Gemini description response.")
        
        # Truncate to avoid URL length issues with Pollinations
        subject_description = subject_description.strip().replace('\n', ' ')[:250]
        logger.info(f"Subject description: {subject_description}")

        # ---- STEP 2: Use Pollinations.ai (FREE, no API key) to generate images ----
        import urllib.parse
        import time
        
        def call_pollinations_api(prompt_text, retry=0):
            # Truncate prompt to prevent URL-too-long errors
            prompt_text = prompt_text[:500]
            encoded_prompt = urllib.parse.quote(prompt_text)
            url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true&seed={int(time.time()) + retry}"
            
            response = requests.get(url, timeout=120)
            
            if response.status_code == 500 and retry < 2:
                logger.warning(f"Pollinations returned 500, retrying ({retry + 1}/2)...")
                time.sleep(3)
                return call_pollinations_api(prompt_text, retry + 1)
            
            if response.status_code != 200:
                raise Exception(f"Pollinations API Error ({response.status_code}): {response.text[:200]}")
            
            if not response.headers.get('content-type', '').startswith('image'):
                raise Exception("Pollinations API did not return an image.")
                
            return response.content

        # Loop through each selected perspective and generate an image
        for i, perspective in enumerate(perspectives):
            prompt = f"Photorealistic {perspective} shot, {subject_description}"
            logger.info(f"Step 2: Generating '{perspective}' for job {job_id} using Pollinations.ai...")
            
            img_bytes = call_pollinations_api(prompt)
            
            var_file = ContentFile(img_bytes, name=f"{job.id}_{i}.png")
            GeneratedVariation.objects.create(
                job=job,
                name=perspective,
                image=var_file
            )

        job.status = 'COMPLETED'
        job.save()
        logger.info(f"Job {job_id} completed successfully with {len(perspectives)} variations.")
        
    except Exception as e:
        logger.exception(f"Job {job_id} failed: {str(e)}")
        job = ImageVariationJob.objects.get(id=job_id)
        job.status = 'FAILED'
        job.error_message = str(e)
        job.save()
