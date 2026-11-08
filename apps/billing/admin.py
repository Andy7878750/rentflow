from django.contrib import admin

from .models import Meter, Receipt


class MeterInline(admin.TabularInline):
    model = Meter
    extra = 0


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ['name', 'property', 'split', 'metered', 'amount_mode']
    list_filter = ['property', 'kind']
    inlines = [MeterInline]
