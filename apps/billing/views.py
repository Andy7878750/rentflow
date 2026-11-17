from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.forms.utils import ErrorDict
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
    if property_obj.is_owner_used:
        return False
    # «Своя формула»: each by his own meters can also be switched off (the check of the formula window shows it).
    return receipt.split in services.SWITCHABLE_SPLITS or (services.is_formula(receipt) and receipt.split != Receipt.Split.OWNER)


def _receipt_form(request, property_obj, receipt, own_tpl=None, start_meter=None):
    posted = request.POST if request.method == 'POST' else None
    # Back from «+ Добавить счётчик объекта»: the window is drawn again with what was typed, nothing is saved.
    redraw = posted is not None and posted.get('_redraw') == '1'
    # «Счётчик: Да» → the object's meters with a tick: what was posted, else the service's, else the template's kind.
    meter_ids = services.parse_meter_ids(property_obj, posted, receipt)
    if meter_ids is not None:
        checked = set(meter_ids)
        if redraw:
            checked |= set(services.new_meter_ids(property_obj, posted, receipt))
    elif receipt.pk:
        checked = set(receipt.meters.values_list('pk', flat=True))
    elif start_meter is not None and start_meter.pk not in services.busy_meters(receipt):
        checked = {start_meter.pk}  # opened from «Все счётчики»: just this meter switched on
    else:
        checked = set(services.default_meter_ids(receipt))
    picks = services.meter_picks(receipt, checked)
    for pick in picks:
        # Drawn again after a refused save or on the way back: «чей» as it was just chosen, not as it is stored.
        name = f'who_{pick["meter"].pk}'
        if posted is not None and name in posted and not pick['busy']:
            pick['who_value'] = posted.get(name, '')
            pick['owner_key'] = 'tenant' if pick['who_value'] else 'common'
        mode = posted.get(f'mode_{pick["meter"].pk}') if posted is not None else None
        if mode in Receipt.InputMode.values and not pick['busy']:
            pick['mode'] = mode
    ticked = [pick['meter'] for pick in picks if pick['checked']]
    # The layout follows the ticks and their «чей» (hidden radios kept in step by app.js), so «Делим» is right from the start.
    owners = {pick['owner_key'] for pick in picks if pick['checked']}
    meter_layout = (Receipt.Layout.BOTH if len(owners) > 1 else Receipt.Layout.TENANTS if owners == {'tenant'}
                    else Receipt.Layout.COMMON)
    if posted is None and receipt.metered and not property_obj.is_owner_used:
        receipt.layout = meter_layout
        services.normalize(receipt)

    form = ReceiptForm(posted, instance=receipt)
    tariffs = services.parse_tariffs(posted) if posted is not None else None
    excluded = services.parse_excluded(property_obj, posted)
    meters_error, missing, mixed = '', [], False
    if redraw:
        form.is_valid()
        form._errors = ErrorDict()  # half-typed is fine here: no red fields on the way back
    elif posted is not None and form.is_valid() and form.instance.metered:
        if not ticked:
            meters_error = 'Отметьте счётчики, по которым считается услуга.'
        else:
            missing = services.missing_tariffs(form.instance, ticked, tariffs)
            if missing:
                meters_error = 'Укажите тариф — по нему считается сумма.'
        # Common meters and the tenants' own ones don't go in one service: the hint under the meters turns red.
        mixed = not property_obj.is_owner_used and services.mixed_owners(ticked, posted)
    elif posted is not None and form.is_valid() and services.by_usage(form.instance) and not ticked:
        meters_error = 'Отметьте счётчики, по расходу которых делится сумма.'
    # «Своя формула»: the formula window's state comes as JSON; checked (units, who pays) before saving.
    formula_data = services.parse_formula(posted)
    formula_error = ''
    if posted is not None and not redraw and form.is_valid() and services.is_formula(form.instance):
        formula_error = services.formula_problem(property_obj, formula_data or {}, receipt)
    if posted is not None and not redraw and not meters_error and not mixed and not formula_error and form.is_valid():
        is_new = receipt.pk is None
        # The form has already written the new name into the receipt: the tile is found by the stored one.
        old_name = Receipt.objects.filter(pk=receipt.pk).values_list('name', flat=True).first() if receipt.pk else None
        old_tile = property_obj.service_templates.filter(name=old_name).first() if old_name else None
        if form.instance.metered or services.by_usage(form.instance):
            services.apply_meter_owners(property_obj, posted)  # «чей» of each meter row
        services.save_receipt(form.save(commit=False), meter_ids=[m.pk for m in ticked], tariffs=tariffs, excluded=excluded,
                              formula=formula_data)
        verb = 'добавлена' if is_new else 'сохранена'
        message = f'Услуга «{receipt.name}» {verb}.'
        if 'tile_shown' in posted:
            as_tile = posted.get('as_tile') == '1'
            if old_tile and old_tile.name != receipt.name and as_tile:
                old_tile.delete()  # renamed: the tile follows the service
            services.save_as_tile(receipt, as_tile)
            if as_tile:
                message = f'Услуга «{receipt.name}» {verb} и стала плашкой в «Новой услуге».'
        return _done(request, property_obj, message)

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
        'kind_tiles': None if receipt.pk else services.template_tiles(property_obj, None if own_tpl else receipt.kind),
        'own_tiles': None if receipt.pk else services.own_tiles(property_obj, own_tpl),
        'own_tpl': own_tpl,
        # «Своя»: save it as a tile too? On when a tile with its name is there already.
        'tile_shown': receipt.kind == Receipt.Kind.CUSTOM,
        'tile_on': (posted.get('as_tile') == '1') if posted is not None and 'tile_shown' in posted
                   else bool(own_tpl or services.tile_of(receipt)),
        'known_meters': ','.join(str(pick['meter'].pk) for pick in picks),
        'meters_error': meters_error,
        'mixed': mixed,
        'formula_ctx': services.formula_context(receipt, formula_data),
        'formula_error': formula_error,
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
    template = services.owner_template(property_obj, request.GET.get('tpl') or request.POST.get('tpl'))
    receipt = services.new_receipt(property_obj, request.GET.get('kind') or request.POST.get('kind'), template)
    meter_pk = request.GET.get('meter', '')
    start_meter = property_obj.meters.filter(pk=meter_pk).first() if meter_pk.isdigit() else None
    if start_meter is not None and not receipt.metered:
        receipt.metered = True  # «Своя» from a meter: by meters straight away
    return _receipt_form(request, property_obj, receipt, template, start_meter)


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
    return {
        'table': services.payment_table(request.user, month), 'month': property_services.month_param(month),
        'month_label': property_services.month_label(month),
        'prev_month': property_services.month_param(property_services.shift_month(month, -1)),
        'next_month': property_services.month_param(property_services.shift_month(month, 1)),
    }


@login_required
def payment_list(request):
    """«Оплаты»: the owner's payments to the providers for a month — a card per object, a tile per service."""
    month = property_services.parse_month(request.GET.get('month'))
    return render(request, 'billing/payment_list.html', _payment_context(request, month))


@login_required
@require_POST
def payment_edit(request, pk, month):
    """A tile of «Оплаты» marked right in place (no window): `paid` 1 / 0 with the date `paid_on` (today when
    empty), or just the remark `note`. Answers with the board drawn anew (the sums on top, the tiles)."""
    receipt = _own_receipt(request, pk)
    month_date = property_services.parse_month(month)
    if 'paid' in request.POST:
        paid_on = None
        if request.POST['paid'] == '1':
            paid_on = services.parse_day(request.POST.get('paid_on')) or date.today()
        services.save_payment(receipt, month_date, paid_on, request.POST.get('note'))
    elif 'note' in request.POST:
        services.save_payment_note(receipt, month_date, request.POST['note'])
    return render(request, 'billing/_payment_board.html', _payment_context(request, month_date))


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
