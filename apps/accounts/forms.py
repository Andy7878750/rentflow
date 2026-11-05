from allauth.account.forms import SignupForm
from django import forms
from django.utils import timezone

from .models import Profile


class CustomSignupForm(SignupForm):
    full_name = forms.CharField(label='Как к вам обращаться', max_length=150)
    privacy_consent = forms.BooleanField(
        label='Согласен с политикой конфиденциальности и даю согласие на обработку персональных данных',
        required=True,
    )

    field_order = ['full_name', 'email', 'password1', 'privacy_consent']

    def save(self, request):
        user = super().save(request)
        Profile.objects.create(
            user=user,
            full_name=self.cleaned_data['full_name'],
            privacy_consent_at=timezone.now(),
        )
        return user
