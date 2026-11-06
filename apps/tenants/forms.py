from decimal import Decimal

from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory

from apps.properties.forms import PHONE_PLACEHOLDER, add_blank_placeholders
from apps.properties.models import Property

from . import services
from .models import Tenant

DATE_FORMAT = '%d.%m.%Y'
DATE_INPUT_FORMATS = [DATE_FORMAT, '%Y-%m-%d']


class TenantForm(forms.ModelForm):
    # One input for the share; its unit (% or m²) is chosen once for the whole object.
    share = forms.DecimalField(
        label='Доля',
        max_digits=8,
        decimal_places=2,
        min_value=Decimal('0.01'),
        localize=True,
        widget=forms.TextInput(attrs={'inputmode': 'decimal', 'data-share': ''}),
    )

    class Meta:
        model = Tenant
        fields = ['name', 'share', 'phone', 'email', 'contract', 'contract_until']
        widgets = {
            'phone': forms.TextInput(attrs={'type': 'tel', 'placeholder': PHONE_PLACEHOLDER, 'data-phone': ''}),
            'contract': forms.TextInput(attrs={'placeholder': '№ и дата'}),
            # Our own calendar (static/js/app.js) fills it; typing by hand works too.
            'contract_until': forms.DateInput(
                format=DATE_FORMAT,
                attrs={'placeholder': 'дд.мм.гггг', 'inputmode': 'numeric', 'autocomplete': 'off', 'data-date': ''},
            ),
        }

    def __init__(self, *args, share_unit=Property.ShareUnit.PERCENT, **kwargs):
        super().__init__(*args, **kwargs)
        add_blank_placeholders(self)
        self.fields['contract_until'].input_formats = DATE_INPUT_FORMATS
        self.fields['contract_until'].error_messages['invalid'] = 'Введите дату в виде дд.мм.гггг.'
        self.share_unit = share_unit
        if self.instance.pk:
            value = self.instance.area if share_unit == Property.ShareUnit.AREA else self.instance.share_percent
            if value is not None:
                self.initial['share'] = services.plain(value)

    def clean_share(self):
        share = self.cleaned_data['share']
        if self.share_unit == Property.ShareUnit.PERCENT and share > 100:
            raise forms.ValidationError('Доля не может быть больше 100%.')
        return share


class BaseTenantFormSet(BaseInlineFormSet):
    # Set by the view from the object form before validation.
    share_unit = Property.ShareUnit.PERCENT
    total_area = None

    def active_forms(self):
        """Filled-in rows that are not marked for removal."""
        return [
            form for form in self.forms
            if form not in self.deleted_forms and (form.instance.pk or form.has_changed())
        ]

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        values = [form.cleaned_data['share'] for form in self.active_forms()]
        if not values:
            return
        error = services.share_error(values, self.share_unit, self.total_area)
        if error:
            raise forms.ValidationError(error)


TenantFormSet = inlineformset_factory(
    Property,
    Tenant,
    form=TenantForm,
    formset=BaseTenantFormSet,
    extra=1,
    can_delete=True,
)
