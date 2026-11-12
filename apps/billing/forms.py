from django import forms

from apps.properties.models import Property

from .models import Meter, Receipt

# Units offered in the «Единица» menu of metered services.
UNITS = ['кВт·ч', 'м³', 'Гкал', 'ед.']


class ReceiptForm(forms.ModelForm):
    # Radio choices rendered by hand in the template (segmented controls).
    metered = forms.TypedChoiceField(
        choices=[('1', 'Да'), ('0', 'Нет')], coerce=lambda value: value == '1', initial='0',
    )
    zones = forms.TypedChoiceField(
        choices=[('1', 'Однотарифный'), ('2', 'День / ночь')], coerce=int, initial='1', required=False, empty_value=1,
    )

    class Meta:
        model = Receipt
        fields = [
            'name', 'provider', 'metered', 'zones', 'unit', 'tariff', 'tariff_night', 'input_mode', 'layout',
            'split', 'amount_mode', 'fixed_amount',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': ' ', 'maxlength': 100}),
            'provider': forms.TextInput(attrs={'placeholder': ' '}),
            'unit': forms.HiddenInput(),
            # Compact fields of «Как считаем»: the unit and currency are written inside the frame.
            'tariff': forms.TextInput(attrs={'placeholder': '0,00', 'inputmode': 'decimal', 'aria-label': 'Тариф'}),
            'tariff_night': forms.TextInput(attrs={'placeholder': '0,00', 'inputmode': 'decimal', 'aria-label': 'Тариф ночь'}),
            'fixed_amount': forms.TextInput(attrs={'placeholder': '0,00', 'inputmode': 'decimal', 'aria-label': 'Сумма в месяц'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial['metered'] = '1' if self.instance.metered else '0'
        self.initial['zones'] = str(self.instance.zones or 1)
        for name in ('tariff', 'tariff_night', 'fixed_amount'):
            self.fields[name].localize = True
        # Hidden sections still post their radios, but a service without a meter has no layout.
        self.fields['layout'].required = False
        self.fields['input_mode'].required = False
        # «По показаниям» is no button: with the tenants' own meters no split radio is checked.
        self.fields['split'].required = False
        # Left empty — the template's name («Электричество»); no error for that.
        self.fields['name'].required = False

    def clean_name(self):
        name = (self.cleaned_data.get('name') or '').strip()
        return name or Receipt.Kind(self.instance.kind or Receipt.Kind.CUSTOM).label

    @property
    def units(self):
        current = self['unit'].value() or ''
        return UNITS if not current or current in UNITS else [current, *UNITS]

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('input_mode'):
            cleaned['input_mode'] = Receipt.InputMode.READINGS
        if not cleaned.get('layout'):
            cleaned['layout'] = Receipt.Layout.COMMON
        if not cleaned.get('split'):
            own_meters = cleaned.get('metered') and cleaned['layout'] != Receipt.Layout.COMMON
            cleaned['split'] = Receipt.Split.METERS if own_meters else Receipt.Split.SHARES
        # From the service window the tariff and unit come with each meter (checked in the view).
        if cleaned.get('metered') and 'meter_kind' not in self.data and 'meters_shown' not in self.data:
            if not cleaned.get('unit'):
                self.add_error('unit', 'Выберите единицу.')
            if cleaned.get('tariff') is None:
                self.add_error('tariff', 'Укажите тариф — по нему считается сумма.')
            if cleaned.get('zones') == 2 and cleaned.get('tariff_night') is None:
                self.add_error('tariff_night', 'Укажите ночной тариф.')
        elif cleaned.get('amount_mode') == Receipt.AmountMode.FIXED:
            amount = cleaned.get('fixed_amount')
            if amount is None or amount <= 0:
                self.add_error('fixed_amount', 'Укажите сумму, которая приходит каждый месяц.')
        return cleaned


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
        for name in ('initial', 'initial_night'):
            self.fields[name].localize = True
            self.fields[name].widget.is_localized = True
            self.fields[name].error_messages['invalid'] = 'Введите число.'
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
