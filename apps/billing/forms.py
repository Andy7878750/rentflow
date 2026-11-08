from django import forms

from .models import Receipt


class ReceiptForm(forms.ModelForm):
    # Radio choices rendered by hand in the template (segmented controls).
    metered = forms.TypedChoiceField(
        choices=[('0', 'Нет'), ('1', 'Есть')], coerce=lambda value: value == '1', initial='0',
    )

    class Meta:
        model = Receipt
        fields = ['name', 'provider', 'metered', 'unit', 'tariff', 'split', 'amount_mode', 'fixed_amount']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': ' ', 'maxlength': 100}),
            'provider': forms.TextInput(attrs={'placeholder': ' '}),
            'unit': forms.TextInput(attrs={'placeholder': ' ', 'maxlength': 10}),
            'tariff': forms.TextInput(attrs={'placeholder': ' ', 'inputmode': 'decimal'}),
            'fixed_amount': forms.TextInput(attrs={'placeholder': ' ', 'inputmode': 'decimal'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial['metered'] = '1' if self.instance.metered else '0'
        self.fields['tariff'].localize = True
        self.fields['fixed_amount'].localize = True

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('amount_mode') == Receipt.AmountMode.FIXED and not cleaned.get('metered'):
            amount = cleaned.get('fixed_amount')
            if amount is None or amount <= 0:
                self.add_error('fixed_amount', 'Укажите сумму, которая приходит каждый месяц.')
        return cleaned
