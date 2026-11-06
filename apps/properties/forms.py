from decimal import Decimal

from django import forms
from django.core.validators import MinValueValidator

from apps.tenants.services import plain

from .models import Property
from .services import clean_kind_name

PHONE_PLACEHOLDER = '+7 (___) ___-__-__ или +код страны'


def add_blank_placeholders(form):
    """Prepare every visible input of our forms.

    - Floating labels need a placeholder: CSS sees an empty field by it.
    - The browser must not fill in the landlord's own login, address or phone:
      these fields are about the object, the management company and tenants.
    """
    for field in form.fields.values():
        if getattr(field.widget, 'input_type', None) not in (None, 'hidden', 'radio', 'checkbox'):
            field.widget.attrs.setdefault('placeholder', ' ')
            field.widget.attrs.setdefault('autocomplete', 'off')
            field.widget.attrs.setdefault('data-1p-ignore', '')       # 1Password
            field.widget.attrs.setdefault('data-lpignore', 'true')    # LastPass


class PropertyForm(forms.ModelForm):
    class Meta:
        model = Property
        fields = [
            'kind', 'custom_kind', 'name', 'address', 'floor', 'area',
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
            'cabinet_login': forms.TextInput,
            # A plain text field drawn as dots (CSS .masked), not type=password:
            # a password field makes the browser treat the whole form as a login form
            # and fill in the landlord's own saved e-mail and password.
            'password_hint': forms.TextInput(attrs={'placeholder': 'сам пароль не храним', 'class': 'masked'}),
            # Set by the custom «Тип» dropdown and the unit picker inside the share fields.
            'kind': forms.HiddenInput,
            'custom_kind': forms.HiddenInput,
            'occupancy': forms.RadioSelect,
            'share_unit': forms.HiddenInput,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_blank_placeholders(self)
        # Accept "45,5" as well as "45.5".
        self.fields['area'].localize = True
        self.fields['area'].widget.is_localized = True
        self.fields['area'].validators.append(MinValueValidator(Decimal('0.01')))
        if self.instance.area is not None:
            self.initial['area'] = plain(self.instance.area)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('kind') == Property.Kind.CUSTOM:
            cleaned['custom_kind'] = clean_kind_name(cleaned.get('custom_kind'))
            if not cleaned['custom_kind']:
                self.add_error('kind', 'Выберите тип или добавьте свой вариант.')
        else:
            cleaned['custom_kind'] = ''
        return cleaned
