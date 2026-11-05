from django import forms

from .models import Property


class PropertyForm(forms.ModelForm):
    class Meta:
        model = Property
        fields = ['name', 'kind', 'address', 'management_company', 'management_phone']
