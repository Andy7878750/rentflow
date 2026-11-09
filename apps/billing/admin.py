from django.contrib import admin

from .models import Meter, Receipt


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ['name', 'property', 'split', 'metered', 'amount_mode']
    list_filter = ['property', 'kind']
    filter_horizontal = ['meters']


@admin.register(Meter)
class MeterAdmin(admin.ModelAdmin):
    list_display = ['name', 'property', 'kind', 'tenant', 'serial']
    list_filter = ['property', 'kind']
