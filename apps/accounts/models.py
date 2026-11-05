from django.conf import settings
from django.db import models


class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    full_name = models.CharField(max_length=150)
    privacy_consent_at = models.DateTimeField()

    def __str__(self):
        return self.full_name
