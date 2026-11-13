from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.properties import services as property_services
from apps.properties.models import Property
from apps.properties.views import modal_back_url, object_page_context

from . import services
from .forms import ReceiptForm
from .models import Meter, Receipt


def _done(request, property_obj, message):
    """Back with a toast: in the modal, to the page it was opened on; otherwise to the object page."""
    messages.success(request, message)
    url = reverse('property_detail', args=[property_obj.pk])
    if request.headers.get('X-Modal'):
        return HttpResponse(status=204, headers={'X-Modal-Redirect': modal_back_url(request) or url})
    return redirect(url)


def _payers_switchable(receipt, property_obj):
    """«Кто платит»: a switch at each tenant only when the sum is split between them."""
    return not property_obj.is_owner_used and receipt.split in services.SWITCHABLE_SPLITS


def _receipt_form(request, property_obj, receipt):
    posted = request.POST if request.method == 'POST' else None
    # «Счётчик: Да» → the object's meters with a tick: what was posted, else the service's, else the template's kind.
    meter_ids = services.parse_meter_ids(property_obj, posted)
    if meter_ids is not None:
        checked = set(meter_ids)
    elif receipt.pk:
        checked = set(receipt.meters.values_list('pk', flat=True))
    else:
        checked = set(services.default_meter_ids(receipt))
    picks = services.meter_picks(receipt, checked)
    ticked = [pick['meter'] for pick in picks if pick['checked']]
    # The layout follows the ticks (hidden radios kept in step by app.js), so «Делим» is right from the start.
    meter_layout = services._layout_of(ticked) if ticked else Receipt.Layout.COMMON
    if posted is None and receipt.metered and not property_obj.is_owner_used:
        receipt.layout = meter_layout
        services.normalize(receipt)

    form = ReceiptForm(posted, instance=receipt)
    tariffs = services.parse_tariffs(posted) if posted is not None else None
    excluded = services.parse_excluded(property_obj, posted)
    meters_error, missing = '', []
    if posted is not None and form.is_valid() and form.instance.metered:
        if not ticked:
            meters_error = 'Отметьте счётчики, по которым считается услуга.'
        else:
            missing = services.missing_tariffs(form.instance, ticked, tariffs)
            if missing:
                meters_error = 'Укажите тариф — по нему считается сумма.'
    if posted is not None and not meters_error and form.is_valid():
        is_new = receipt.pk is None
        if form.instance.metered:
            services.apply_meter_owners(property_obj, posted)  # «чей» of each meter row
        services.save_receipt(form.save(commit=False), meter_ids=[m.pk for m in ticked], tariffs=tariffs, excluded=excluded)
        verb = 'добавлена' if is_new else 'сохранена'
        return _done(request, property_obj, f'Услуга «{receipt.name}» {verb}.')

    shown = [pick for pick in picks if pick['shown']]
    rows = {row['key']: row for row in services.tariff_rows(form.instance, shown, tariffs, missing)}
    for pick in shown:
        pick['tariff'] = rows.get(pick['key'])
    template = 'billing/_receipt_form.html' if request.headers.get('X-Modal') else 'billing/receipt_form.html'
    return render(request, template, {
        'form': form,
        'receipt': receipt,
        'property': property_obj,
        'warning': services.split_warning(form.instance),
        # New service: the templates on top of the same window; picking one refills the fields below.
        'kind_tiles': None if receipt.pk else services.template_tiles(property_obj, receipt.kind),
        'meters_error': meters_error,
        'payers': services.payer_preview(services.normalize(form.instance), excluded),
        'payers_switchable': _payers_switchable(form.instance, property_obj),
        'tenants': property_obj.tenants.all(),
        # Only the template's kind of meters (and the ticked ones) are listed; each row with its own tariff.
        'meter_picks': shown,
        'meter_tenants': list(property_obj.tenants.all()),
        'meter_layout': meter_layout,
        'meters_label': services.meters_label(len(ticked)),
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
    """«Кто платит» → «Арендаторы» of the service window, recounted while the form is filled in (nothing is saved)."""
    property_obj = get_object_or_404(Property, pk=property_pk, owner=request.user)
    pk = request.POST.get('receipt')
    if pk:
        receipt = get_object_or_404(Receipt, pk=pk, property=property_obj)
    else:
        receipt = services.new_receipt(property_obj, request.POST.get('kind'))
    form = ReceiptForm(request.POST, instance=receipt)
    form.is_valid()
    payers = services.payer_preview(services.normalize(form.instance), services.parse_excluded(property_obj, request.POST))
    return render(request, 'billing/_payers.html', {
        'payers': payers, 'receipt': receipt, 'property': property_obj,
        'payers_switchable': _payers_switchable(form.instance, property_obj),
    })


def _meter_row(request):
    """The posted row of «Счётчики»: meter_kind → kind, …"""
    return {key: request.POST.get(f'meter_{key}', '') for key in services.METER_FIELDS}


@login_required
@require_POST
def meter_save(request, property_pk):
    """«✓» at the end of a meter row: save the meter to the object, answer with its id."""
    property_obj = get_object_or_404(Property, pk=property_pk, owner=request.user)
    meter = services.save_meter(property_obj, _meter_row(request))
    return JsonResponse({'id': meter.pk})


@login_required
@require_POST
def meter_delete(request, pk):
    """«×» at the end of a meter row."""
    meter = get_object_or_404(Meter, pk=pk, property__owner=request.user)
    receipt = request.POST.get('receipt')
    deleted = services.delete_meter(meter, keep_for=int(receipt) if receipt and receipt.isdigit() else None)
    return JsonResponse({'deleted': deleted})


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
