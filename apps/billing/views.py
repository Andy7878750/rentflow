from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.properties import services as property_services
from apps.properties.models import Property
from apps.properties.views import object_page_context

from . import services
from .forms import ReceiptForm
from .models import Receipt


def _done(request, property_obj, message):
    """Back to the object page with a toast; in the modal, tell app.js where to go."""
    messages.success(request, message)
    url = reverse('property_detail', args=[property_obj.pk])
    if request.headers.get('X-Modal'):
        return HttpResponse(status=204, headers={'X-Modal-Redirect': url})
    return redirect(url)


def _receipt_form(request, property_obj, receipt):
    form = ReceiptForm(request.POST or None, instance=receipt)
    if request.method == 'POST' and form.is_valid():
        is_new = receipt.pk is None
        services.save_receipt(form.save(commit=False))
        verb = 'добавлена' if is_new else 'сохранена'
        return _done(request, property_obj, f'Квитанция «{receipt.name}» {verb}.')

    template = 'billing/_receipt_form.html' if request.headers.get('X-Modal') else 'billing/receipt_form.html'
    return render(request, template, {
        'form': form,
        'receipt': receipt,
        'property': property_obj,
        'warning': services.split_warning(form.instance),
        'split_choices': [
            choice for choice in Receipt.Split.choices
            if not (property_obj.is_owner_used and choice[0] not in (Receipt.Split.METERS, Receipt.Split.OWNER))
        ],
    })


@login_required
def receipt_create(request, property_pk):
    property_obj = get_object_or_404(Property, pk=property_pk, owner=request.user)
    receipt = services.new_receipt(property_obj, request.GET.get('kind') or request.POST.get('kind'))
    return _receipt_form(request, property_obj, receipt)


def _own_receipt(request, pk):
    return get_object_or_404(Receipt.objects.select_related('property'), pk=pk, property__owner=request.user)


@login_required
def receipt_edit(request, pk):
    receipt = _own_receipt(request, pk)
    return _receipt_form(request, receipt.property, receipt)


@login_required
def receipt_delete(request, pk):
    receipt = _own_receipt(request, pk)
    if request.method == 'POST':
        receipt.delete()
        return _done(request, receipt.property, f'Квитанция «{receipt.name}» удалена.')
    template = 'billing/_receipt_delete.html' if request.headers.get('X-Modal') else 'billing/receipt_delete.html'
    return render(request, template, {'receipt': receipt, 'property': receipt.property})


@login_required
def receipt_pick(request, property_pk):
    """«+ Квитанция»: choose a ready-made receipt or your own."""
    property_obj = get_object_or_404(Property, pk=property_pk, owner=request.user)
    template = 'billing/_receipt_pick.html' if request.headers.get('X-Modal') else 'billing/receipt_pick.html'
    return render(request, template, {
        'property': property_obj,
        'missing_kinds': [(kind, kind.label) for kind in services.missing_kinds(property_obj)],
    })


@login_required
@require_POST
def month_save(request, property_pk):
    """Save the month's amounts and readings. From app.js it answers with the refreshed page."""
    property_obj = get_object_or_404(Property, pk=property_pk, owner=request.user)
    month = property_services.parse_month(request.POST.get('month'))
    services.save_month_input(property_obj, month, request.POST)
    if request.POST.get('beacon'):
        return HttpResponse(status=204)
    if request.headers.get('X-Live'):
        return render(request, 'properties/detail.html', object_page_context(request, property_obj, month))
    messages.success(request, 'Сохранено.')
    url = reverse('property_detail', args=[property_obj.pk]) + f'?month={property_services.month_param(month)}'
    return redirect(url)
