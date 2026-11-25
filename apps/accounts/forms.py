from allauth.account.forms import AddEmailForm, SignupForm
from django import forms
from django.utils import timezone

from config.validators import use_email_rule

from .models import Profile


class CustomAddEmailForm(AddEmailForm):
    """«Новая почта» — the same e-mail rule as everywhere on the site."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        use_email_rule(self, 'email')


class CustomSignupForm(SignupForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        use_email_rule(self, 'email')  # the same rule as everywhere on the site (2026-11-25)

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
