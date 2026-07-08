import uuid
from django.db import models

class ImageVariationJob(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    original_image = models.ImageField(upload_to='creative_image/originals/')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    left_profile_image = models.ImageField(upload_to='creative_image/variations/', null=True, blank=True)
    right_profile_image = models.ImageField(upload_to='creative_image/variations/', null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Job {self.id} - {self.status}"

class GeneratedVariation(models.Model):
    job = models.ForeignKey(ImageVariationJob, on_delete=models.CASCADE, related_name='variations')
    name = models.CharField(max_length=50) # e.g. "Closeup", "Back view"
    image = models.ImageField(upload_to='creative_image/variations/')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} for Job {self.job_id}"
