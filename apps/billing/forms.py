from datetime import date

from django import forms

from apps.properties.models import Property

from .models import Meter, Receipt

# ---------------------------------------------------------------------------
# Meters of the object («Счётчики» in the object window, one small window per meter)
# ---------------------------------------------------------------------------

# Start-reading units for a meter of the owner's own kind.
METER_UNITS = ['кВт·ч', 'м³', 'Гкал', 'л', 'шт.']


class LooseDecimalField(forms.DecimalField):
    """A number as people type it: «12 450», «12450,5», «12 450.5»."""

    def to_python(self, value):
        if isinstance(value, str):
            value = value.replace(' ', '').replace(' ', '').replace(',', '.')
        return super().to_python(value)


class MeterForm(forms.ModelForm):
    """One meter of the premises: what it measures, №, one tariff or day / night, the start reading.

    Who pays by it is not asked here: it is ticked in the tenant's window and posted as `owner`
    («pk:<tenant id>», «new:<tenant form index>», «free» or empty — a common meter).
    """

    day_night = forms.TypedChoiceField(
        choices=[('0', 'Однотарифный'), ('1', 'День / ночь')], coerce=lambda value: value == '1',
        initial='0', required=False, empty_value=False,
    )
    owner = forms.CharField(required=False, widget=forms.HiddenInput)
    # The meter's own tariff (2026-11-19): kept with history (MeterTariff) — a change starts this month.
    tariff = LooseDecimalField(required=False, max_digits=10, decimal_places=4,
                               widget=forms.TextInput(attrs={'inputmode': 'decimal'}))
    tariff_night = LooseDecimalField(required=False, max_digits=10, decimal_places=4,
                                     widget=forms.TextInput(attrs={'inputmode': 'decimal'}))

    class Meta:
        model = Meter
        fields = ['kind', 'name', 'unit', 'serial', 'day_night', 'initial', 'initial_night']
        widgets = {
            'kind': forms.HiddenInput(),
            'name': forms.HiddenInput(),
            'unit': forms.HiddenInput(),
            'initial': forms.TextInput(attrs={'inputmode': 'decimal'}),
            'initial_night': forms.TextInput(attrs={'inputmode': 'decimal'}),
        }
        labels = {'serial': '№ счётчика', 'initial': 'Начальное', 'initial_night': 'Начальное · ночь'}
        field_classes = {'initial': LooseDecimalField, 'initial_night': LooseDecimalField}

    def __init__(self, *args, **kwargs):
        from apps.properties.forms import add_blank_placeholders

        from . import services

        super().__init__(*args, **kwargs)
        add_blank_placeholders(self)
        for name in ('initial', 'initial_night', 'tariff', 'tariff_night'):
            self.fields[name].localize = True
            self.fields[name].widget.is_localized = True
            self.fields[name].error_messages['invalid'] = 'Введите число.'
        meter = self.instance
        if meter.pk and not self.is_bound:
            now = services.meter_tariff_at(meter, services.first_of_month(date.today()))
            day, night = (now.tariff, now.tariff_night) if now else (meter.tariff, meter.tariff_night)
            if day is not None:
                self.initial['tariff'] = services.fmt_number(day)
            if night is not None:
                self.initial['tariff_night'] = services.fmt_number(night)
        self.fields['kind'].required = False
        self.fields['name'].required = False
        self.fields['unit'].required = False
        meter = self.instance
        self.initial['day_night'] = '1' if meter.day_night else '0'
        for name in ('initial', 'initial_night'):
            value = getattr(meter, name)
            if value is not None and not self.is_bound:
                self.initial[name] = services.fmt_number(value)  # 251.000 → «251», 2584 → «2 584»
        if meter.tenant_id:
            self.initial['owner'] = f'pk:{meter.tenant_id}'
        elif meter.vacant:
            self.initial['owner'] = 'free'
        if not meter.pk and not self.initial.get('name'):
            # A new meter: electricity by default, as the first item of the menu.
            self.initial.update({'kind': Receipt.Kind.ELECTRICITY, 'name': 'Электричество', 'unit': 'кВт·ч'})

    def clean(self):
        from . import services

        cleaned = super().clean()
        kinds = {kind: (name, unit) for kind, name, unit in services.METER_KINDS}
        name = (cleaned.get('name') or '').strip()[:100]
        kind = cleaned.get('kind')
        if kind not in kinds or kind == Receipt.Kind.CUSTOM:
            kind = Receipt.Kind.CUSTOM
        cleaned['kind'] = kind
        cleaned['name'] = name or (kinds[kind][0] if kind in kinds else services.DEFAULT_METER_NAME)
        if kind in kinds:
            cleaned['unit'] = kinds[kind][1]  # ready-made kinds keep their own unit
        elif not cleaned.get('unit'):
            cleaned['unit'] = METER_UNITS[0]
        if cleaned.get('initial') is None and 'initial' not in self.errors:
            self.add_error('initial', 'Укажите начальное показание.')
        if cleaned.get('day_night'):
            if cleaned.get('initial_night') is None and 'initial_night' not in self.errors:
                self.add_error('initial_night', 'Укажите начальное показание ночью.')
        else:
            cleaned['initial_night'] = None
            cleaned['tariff_night'] = None
        return cleaned

    @property
    def units(self):
        current = self['unit'].value() or ''
        return METER_UNITS if not current or current in METER_UNITS else [current, *METER_UNITS]


class BaseMeterFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        for form in self.deleted_forms:
            meter = form.instance
            if not meter.pk:
                continue
            names = list(meter.receipts.values_list('name', flat=True))
            if names:
                services_list = ', '.join(f'«{name}»' for name in names)
                raise forms.ValidationError(
                    f'Счётчиком «{meter.name}» пользуется услуга {services_list} — сначала уберите его из услуги.')


MeterFormSet = forms.inlineformset_factory(
    Property, Meter, form=MeterForm, formset=BaseMeterFormSet, extra=0, can_delete=True)
