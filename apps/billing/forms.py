from django import forms

from .models import Receipt

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
        if cleaned.get('metered') and 'meter_kind' not in self.data:
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
