from decimal import Decimal

from django import forms
from django.core.validators import MinValueValidator

from apps.tenants.services import plain

from .models import Property

PHONE_PLACEHOLDER = '+7 (___) ___-__-__ или +код страны'


class PropertyForm(forms.ModelForm):
    class Meta:
        model = Property
        fields = [
            'kind', 'name', 'address', 'floor', 'area',
            'management_company', 'management_phone', 'management_email',
            'cabinet_url', 'cabinet_login', 'password_hint',
            'occupancy', 'share_unit',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Например, Королёва 61'}),
            'area': forms.TextInput(attrs={'inputmode': 'decimal', 'data-total-area': ''}),
            'management_company': forms.TextInput(attrs={'placeholder': 'Название управляющей компании'}),
            'management_phone': forms.TextInput(attrs={'type': 'tel', 'placeholder': PHONE_PLACEHOLDER, 'data-phone': ''}),
            'management_email': forms.EmailInput(attrs={'placeholder': 'name@mail.ru'}),
            'cabinet_url': forms.URLInput(attrs={'placeholder': 'https://'}),
            'cabinet_login': forms.TextInput(attrs={'autocomplete': 'off'}),
            'password_hint': forms.PasswordInput(
                render_value=True,
                attrs={'placeholder': 'сам пароль не храним', 'autocomplete': 'off'},
            ),
            'occupancy': forms.RadioSelect,
            'share_unit': forms.RadioSelect,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Accept "45,5" as well as "45.5".
        self.fields['area'].localize = True
        self.fields['area'].widget.is_localized = True
        self.fields['area'].validators.append(MinValueValidator(Decimal('0.01')))
        if self.instance.area is not None:
            self.initial['area'] = plain(self.instance.area)
