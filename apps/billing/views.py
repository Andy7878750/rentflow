from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.properties import services as property_services
from apps.properties.models import Property
from apps.properties.views import modal_back_url, object_page_context

from . import services
from .forms import ReceiptForm
from .models import Receipt


def _done(request, property_obj, message):
    """Back with a toast: in the modal, to the page it was opened on; otherwise to the object page."""
    messages.success(request, message)
    url = reverse('property_detail', args=[property_obj.pk])
    if request.headers.get('X-Modal'):
        return HttpResponse(status=204, headers={'X-Modal-Redirect': modal_back_url(request) or url})
    return redirect(url)


def _preview(form, receipt):
    """The receipt as the form describes it now, unsaved — for «Формула»."""
    if form.is_bound:
        form.is_valid()
        return form.instance
    return receipt


def _receipt_form(request, property_obj, receipt):
    form = ReceiptForm(request.POST or None, instance=receipt)
    if request.method == 'POST' and form.is_valid():
        is_new = receipt.pk is None
        details = services.parse_meter_details(property_obj, request.POST)
        services.save_receipt(form.save(commit=False), meter_details=details)
        verb = 'добавлена' if is_new else 'сохранена'
        return _done(request, property_obj, f'Услуга «{receipt.name}» {verb}.')

    template = 'billing/_receipt_form.html' if request.headers.get('X-Modal') else 'billing/receipt_form.html'
    return render(request, template, {
        'form': form,
        'receipt': receipt,
        'property': property_obj,
        'warning': services.split_warning(form.instance),
        # New service: the templates on top of the same window; picking one refills the fields below.
        'kind_tiles': None if receipt.pk else services.template_tiles(property_obj, receipt.kind),
        'formula': services.formula_example(services.normalize(_preview(form, receipt)), request.POST.get('formula_for')),
        'tenants': property_obj.tenants.all(),
        'meter_rows': services.meter_rows(receipt, request.POST if request.method == 'POST' else None),
        'layout_choices': Receipt.Layout.choices,
        # By readings is not a button any more: it follows from «У каждого свой».
        'split_choices': [
            choice for choice in Receipt.Split.choices
            if choice[0] != Receipt.Split.METERS
            and not (property_obj.is_owner_used and choice[0] != Receipt.Split.OWNER)
        ],
    })


@login_required
def receipt_create(request, property_pk):
    """«+ Добавить услугу»: templates on top, settings below; ?kind=water opens with «Вода» picked."""
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
@require_POST
def receipt_formula(request, property_pk):
    """«Формула» of the service window, recounted while the form is filled in (nothing is saved)."""
    property_obj = get_object_or_404(Property, pk=property_pk, owner=request.user)
    pk = request.POST.get('receipt')
    if pk:
        receipt = get_object_or_404(Receipt, pk=pk, property=property_obj)
    else:
        receipt = services.new_receipt(property_obj, request.POST.get('kind'))
    form = ReceiptForm(request.POST, instance=receipt)
    form.is_valid()
    formula = services.formula_example(services.normalize(form.instance), request.POST.get('formula_for'))
    return render(request, 'billing/_formula.html', {'formula': formula, 'receipt': receipt, 'property': property_obj})


@login_required
def receipt_delete(request, pk):
    receipt = _own_receipt(request, pk)
    if request.method == 'POST':
        services.delete_receipt(receipt)
        return _done(request, receipt.property, f'Услуга «{receipt.name}» удалена.')
    template = 'billing/_receipt_delete.html' if request.headers.get('X-Modal') else 'billing/receipt_delete.html'
    return render(request, template, {'receipt': receipt, 'property': receipt.property})


@login_required
def receipt_add(request):
    """«+ Добавить услугу» in the menu: «К какому объекту?» first, unless there is only one."""
    properties = list(
        Property.objects.filter(owner=request.user).annotate(receipt_count=Count('receipts')).order_by('name')
    )
    for property_obj in properties:
        property_obj.receipt_label = services.services_label(property_obj.receipt_count)
    if len(properties) == 1:
        return receipt_create(request, properties[0].pk)
    template = 'billing/_receipt_add.html' if request.headers.get('X-Modal') else 'billing/receipt_add.html'
    return render(request, template, {'properties': properties})


@login_required
def receipt_list(request):
    """«Услуги»: every service of every object in one table."""
    receipts = (
        Receipt.objects.filter(property__owner=request.user)
        .select_related('property')
        .order_by('property__name', 'property_id', 'created_at', 'id')
    )
    return render(request, 'billing/receipt_list.html', {'receipts': receipts})


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
