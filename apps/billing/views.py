import json
from datetime import date
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from apps.properties import services as property_services
from apps.properties.models import Property
from apps.properties.views import modal_back_url, object_page_context

from . import services, window
from .models import Meter, PayBundle, Receipt


def _done(request, property_obj, message):
    """Back with a toast: in the modal, to the page it was opened on; otherwise to the object page."""
    messages.success(request, message)
    url = reverse('property_detail', args=[property_obj.pk])
    if request.headers.get('X-Modal'):
        return HttpResponse(status=204, headers={'X-Modal-Redirect': modal_back_url(request) or url})
    return redirect(url)


@login_required
def service_window(request, property_pk):
    """«Услуги · <объект>» (2026-11-19): every service of the object in one window, saved by itself.
    ?svc=<id> — open that service; ?mode=<way> — start a new one charged so; ?meter=<id> — a new one by this meter."""
    property_obj = get_object_or_404(Property, pk=property_pk, owner=request.user)
    svc = request.GET.get('svc', '')
    state = window.window_state(property_obj, selected=int(svc) if svc.isdigit() else None)
    mode = request.GET.get('mode', '')
    state['start'] = {'mode': mode if mode in dict(window.MODES) else None,
                      'meter': int(request.GET['meter']) if request.GET.get('meter', '').isdigit() else None}
    template = 'billing/_service_window.html' if request.headers.get('X-Modal') else 'billing/service_window.html'
    return render(request, template, {'property': property_obj, 'state': state})


@login_required
@require_POST
def service_save(request, property_pk):
    """One change in the service window: the service as the window has it → saved; answers with the whole window."""
    property_obj = get_object_or_404(Property, pk=property_pk, owner=request.user)
    try:
        data = json.loads(request.body or b'{}')
        receipt = window.save_service(property_obj, data)
    except (ValueError, TypeError, KeyError) as error:
        message = str(error) if isinstance(error, window.WindowError) else 'Не удалось сохранить.'
        return JsonResponse({'error': message}, status=400)
    return JsonResponse(window.window_state(property_obj, selected=receipt.pk))


def _own_receipt(request, pk):
    return get_object_or_404(Receipt.objects.select_related('property'), pk=pk, property__owner=request.user)


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
        return service_window(request, properties[0].pk)
    template = 'billing/_receipt_add.html' if request.headers.get('X-Modal') else 'billing/receipt_add.html'
    return render(request, template, {'properties': properties, 'pick_url': 'service_window'})


@login_required
def meter_list(request):
    """«Счётчики → Все счётчики»: every meter of every object, read-only; a row opens where it is changed."""
    groups = services.meter_table(request.user)
    return render(request, 'billing/meter_list.html', {
        'groups': groups, 'has_meters': any(group['rows'] for group in groups),
    })


@login_required
@require_POST
def receipt_order(request, property_pk):
    """The service cards of the object page dragged into a new order: `order` — their ids, top to bottom."""
    property_obj = get_object_or_404(Property, pk=property_pk, owner=request.user)
    ids = [int(pk) for pk in request.POST.get('order', '').split(',') if pk.isdigit()]
    services.reorder_receipts(property_obj, ids)
    return JsonResponse({'ok': True})


def _payment_context(request, month):
    table = services.payment_table(request.user, month)
    return {
        'table': table, 'month': property_services.month_param(month),
        'month_label': property_services.month_label(month),
        'prev_param': property_services.month_param(table['prev_month']),
        'prev_name': property_services.month_label(table['prev_month']).split()[0],
        'prev_month': property_services.month_param(property_services.shift_month(month, -1)),
        'next_month': property_services.month_param(property_services.shift_month(month, 1)),
    }


@login_required
@xframe_options_sameorigin  # «Посмотреть» shows it in a modal window (an iframe of our own page)
def bill_print(request, property_pk, payer):
    """«Счёт PDF»: one payer's bill for the month as a PDF file, downloaded (2026-11-17: «просто в pdf, не печать»).
    `payer` — the tenant's id, 0 — the owner («Остаётся на вас»). `?inline=1` — shown in the browser (for «Поделиться»
    it is fetched as a file anyway)."""
    from .pdf import bill_pdf

    property_obj = get_object_or_404(Property, pk=property_pk, owner=request.user)
    month = property_services.parse_month(request.GET.get('month'))
    bill = services.month_bill(property_obj, month)
    found = bill.owner if payer == 0 else bill.payer_for(payer)
    if found is None:
        return HttpResponse(status=404)
    title = found.tenant.name if found.tenant else 'Остаётся на вас'
    label = property_services.month_label(month)
    data = bill_pdf(property_obj, bill, found, title, label, date.today())
    name = services.bill_file_name(title, label)
    response = HttpResponse(data, content_type='application/pdf')
    disposition = 'inline' if request.GET.get('inline') else 'attachment'
    response['Content-Disposition'] = f"{disposition}; filename*=UTF-8''{quote(name)}"
    return response


@login_required
def payment_list(request):
    """«Оплаты»: the owner's payments to the providers for a month — one table, objects × services."""
    month = property_services.parse_month(request.GET.get('month'))
    return render(request, 'billing/payment_list.html', _payment_context(request, month))


@login_required
@require_POST
def payment_edit(request, pk, month):
    """A cell of «Оплаты» marked in place: `paid` 1 / 0 (with `paid_on`, today when empty), or the note (`note` +
    `carry`). `month` — the bill's month (last month's ones are marked from the strip over the table); `view` — the
    month shown. Answers with the board drawn anew."""
    receipt = _own_receipt(request, pk)
    month_date = property_services.parse_month(month)
    if 'paid' in request.POST:
        paid_on = None
        if request.POST['paid'] == '1':
            paid_on = services.parse_day(request.POST.get('paid_on')) or date.today()
        services.save_payment(receipt, month_date, paid_on)
    elif 'note' in request.POST:
        services.save_payment_note(receipt, month_date, request.POST['note'], request.POST.get('carry') == '1')
    view = property_services.parse_month(request.POST.get('view') or month)
    return render(request, 'billing/_payment_board.html', _payment_context(request, view))


def _board(request, view, **headers):
    response = render(request, 'billing/_payment_board.html', _payment_context(request, view))
    for key, value in headers.items():
        response[key] = value
    return response


def _own_bundle(request, pk):
    return get_object_or_404(PayBundle.objects.select_related('property'), pk=pk, property__owner=request.user)


def _tile(request, code):
    """«r12» — a service tile, «b3» — a receipt tile; someone else's — 404."""
    kind, pk = (code or ' ')[0], (code or '')[1:]
    if not pk.isdigit():
        raise Http404
    return _own_bundle(request, int(pk)) if kind == 'b' else _own_receipt(request, int(pk))


@login_required
@require_POST
def payment_bundle_edit(request, pk, month):
    """The check, the date or the note of a receipt tile (several services, one payment): goes to all its services."""
    bundle = _own_bundle(request, pk)
    month_date = property_services.parse_month(month)
    if 'paid' in request.POST:
        paid_on = None
        if request.POST['paid'] == '1':
            paid_on = services.parse_day(request.POST.get('paid_on')) or date.today()
        services.save_bundle_payment(bundle, month_date, paid_on)
    elif 'note' in request.POST:
        services.save_bundle_note(bundle, month_date, request.POST['note'], request.POST.get('carry') == '1')
    return _board(request, property_services.parse_month(request.POST.get('view') or month))


@login_required
@require_POST
def payment_merge(request, month):
    """A tile dropped onto another tile of the same object (`src`, `dst`: «r<id>» / «b<id>»): one receipt. A new one
    is named in the answer's X-Pay-Bundle header — the page opens its window to type the name."""
    source, target = _tile(request, request.POST.get('src')), _tile(request, request.POST.get('dst'))
    if source.property_id != target.property_id:
        return HttpResponse(status=400)
    month_date = property_services.parse_month(month)
    try:
        bundle, made = services.merge_tiles(target.property, month_date, source, target)
    except ValueError:
        return HttpResponse(status=400)
    return _board(request, month_date, **({'X-Pay-Bundle': str(bundle.pk)} if made else {}))


@login_required
@require_POST
def payment_bundle(request, pk):
    """The receipt window: `name` — renamed, `out` — a service taken out (its id), `split` — «Разъединить»."""
    bundle = _own_bundle(request, pk)
    if request.POST.get('split'):
        services.split_bundle(bundle)
    elif request.POST.get('out'):
        receipt = _own_receipt(request, int(request.POST['out'])) if request.POST['out'].isdigit() else None
        if receipt is None or receipt.pay_bundle_id != bundle.pk:
            raise Http404
        services.take_out(bundle, receipt)
    elif 'name' in request.POST:
        services.rename_bundle(bundle, request.POST['name'])
    return _board(request, property_services.parse_month(request.POST.get('view')))


@login_required
def tariff_list(request):
    """«Услуги → Тарифы»: every tariff in force, read-only; a row opens its service, where the tariff is changed."""
    groups = services.tariff_table(request.user)
    return render(request, 'billing/tariff_list.html', {
        'groups': groups, 'has_tariffs': any(group['rows'] for group in groups),
    })


@login_required
@require_POST
def receipt_night_weight(request, pk):
    """«н×0,6» on the object page: how much a night kWh weighs in «По расходу». Empty or 1 — like a day one."""
    receipt = _own_receipt(request, pk)
    text = request.POST.get('value', '').strip()
    weight = services.parse_decimal(text) if text else None
    if text and (weight is None or not (0 < weight <= 10)):
        return JsonResponse({'error': 'Введите число больше нуля — например, 0,6.'}, status=400)
    receipt.night_weight = None if weight is None or weight == 1 else weight
    receipt.save(update_fields=['night_weight'])
    shown = services.fmt_number(receipt.night_weight) if receipt.night_weight is not None else '1'
    return JsonResponse({'value': services.fmt_number(receipt.night_weight) if receipt.night_weight is not None else '',
                         'label': f'н×{shown}'})


@login_required
def meter_remove(request, pk):
    """«Удалить» in «Все счётчики»: a confirmation; a meter a service counts by is not deleted — say where it is."""
    meter = get_object_or_404(Meter.objects.select_related('property'), pk=pk, property__owner=request.user)
    in_services = list(meter.receipts.all())
    if request.method == 'POST' and not in_services:
        name = f'{meter.name} № {meter.serial}' if meter.serial else meter.name
        meter.delete()
        messages.success(request, f'Счётчик «{name}» удалён.')
        url = reverse('meter_list')
        if request.headers.get('X-Modal'):
            return HttpResponse(status=204, headers={'X-Modal-Redirect': modal_back_url(request) or url})
        return redirect(url)
    template = 'billing/_meter_delete.html' if request.headers.get('X-Modal') else 'billing/meter_delete.html'
    return render(request, template, {
        'meter': meter, 'in_services': in_services, 'readings': meter.readings.count(),
    })


@login_required
def meter_add(request):
    """«+ Добавить счётчик» in the menu: meters are added in the object window — «К какому объекту?» first."""
    properties = list(
        Property.objects.filter(owner=request.user).annotate(meter_count=Count('meters')).order_by('name')
    )
    for property_obj in properties:
        property_obj.pick_meta = services.meters_label(property_obj.meter_count) if property_obj.meter_count else 'нет счётчиков'
    if len(properties) == 1:
        from apps.properties.views import property_edit
        return property_edit(request, properties[0].pk)
    template = 'billing/_receipt_add.html' if request.headers.get('X-Modal') else 'billing/receipt_add.html'
    return render(request, template, {
        'properties': properties, 'pick_url': 'property_edit', 'close_url': 'meter_list',
    })


@login_required
def receipt_list(request):
    """«Услуги»: every service of every object in one table."""
    receipts = (
        Receipt.objects.filter(property__owner=request.user)
        .select_related('property')
        .order_by('property__name', 'property_id', 'position', 'created_at', 'id')
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
