from decimal import Decimal
from urllib.parse import urlsplit

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.billing import services as billing_services
from apps.billing.forms import MeterFormSet
from apps.tenants.forms import TenantFormSet

from . import services
from .forms import PropertyForm
from .models import Property, PropertyKind



def modal_back_url(request):
    """The page a modal was opened on (Referer of app.js's request); None if unknown or foreign."""
    referer = request.headers.get('Referer', '')
    safe = url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}, require_https=request.is_secure())
    if not referer or not safe:
        return None
    parts = urlsplit(referer)
    return (parts.path + (f'?{parts.query}' if parts.query else '')) or None


@login_required
def property_list(request):
    month = services.parse_month(request.GET.get('month'))
    properties = list(Property.objects.filter(owner=request.user).prefetch_related('tenants', 'receipts'))
    for property_obj in properties:
        property_obj.setup = services.setup_steps(property_obj)

    # Readings and invoices don't exist yet: zero placeholders until billing lands.
    summary = {
        'to_invoice': Decimal('0.00'),
        'tenants': sum(len(p.tenants.all()) for p in properties),
        'tenants_ready': 0,
        'readings_done': 0,
        'readings_total': len(properties),
        'owner_share': Decimal('0.00'),
    }

    return render(request, 'properties/list.html', {
        'properties': properties,
        'summary': summary,
        'month_label': services.month_label(month),
        'prev_month': services.month_param(services.shift_month(month, -1)),
        'next_month': services.month_param(services.shift_month(month, 1)),
    })


def _property_form(request, property_obj=None):
    """Create or edit an object with its meters and tenants. Renders bare content when opened in the modal.

    Meters and tenants are shown as one-line rows; each is filled in its own small window (app.js),
    and everything is saved together with the object."""
    is_modal = request.headers.get('X-Modal') == '1'
    data = request.POST if request.method == 'POST' else None

    form = PropertyForm(data, instance=property_obj)
    unit = (data or {}).get('share_unit') or (property_obj.share_unit if property_obj else Property.ShareUnit.PERCENT)
    if unit not in Property.ShareUnit.values:
        unit = Property.ShareUnit.PERCENT
    formset = TenantFormSet(
        data,
        instance=property_obj or Property(),
        prefix='tenants',
        form_kwargs={'share_unit': unit},
    )
    formset.extra = 0  # «+ Добавить арендатора» adds a row in its own small window
    # A post without the meters (an old page, a script) leaves them as they are.
    with_meters = data is None or 'meters-TOTAL_FORMS' in data
    meter_formset = MeterFormSet(data if with_meters else None, instance=property_obj or Property(), prefix='meters')

    if data is not None:
        form_ok = form.is_valid()
        meters_ok = meter_formset.is_valid() if with_meters else True
        formset.share_unit = unit
        formset.total_area = form.cleaned_data.get('area')
        owner_used = data.get('occupancy') == Property.Occupancy.OWNER
        tenants_ok = owner_used or formset.is_valid()
        if form_ok and tenants_ok and meters_ok:
            saved = services.save_property(form, formset, request.user, meter_formset if with_meters else None)
            if not property_obj and is_modal:
                # A new object: say what is left to do (receipts and meters) right away.
                return render(request, 'properties/_created.html', {'property': saved})
            # Back to the object cards with a short notice (shown as a toast in app/base.html).
            if property_obj:
                messages.success(request, f'Изменения в «{saved.name}» сохранены.')
            else:
                messages.success(request, f'Объект «{saved.name}» создан.')
            url = reverse('property_list')
            if is_modal:
                return HttpResponse(status=204, headers={'X-Modal-Redirect': url})
            return redirect(url)

    template = 'properties/_form.html' if is_modal else 'properties/form.html'
    return render(request, template, {
        'form': form,
        'formset': formset,
        'meter_formset': meter_formset,
        'meter_kinds': billing_services.meter_kind_options(property_obj or Property(owner=request.user)),
        'property': property_obj,
        'share_unit': unit,
        'kind_choices': [
            (value, label) for value, label in Property.Kind.choices
            if value not in (Property.Kind.OTHER, Property.Kind.CUSTOM)
        ],
        'other_kind_label': Property.Kind.OTHER.label,
        'custom_kinds': PropertyKind.objects.filter(owner=request.user),
    })


@login_required
@require_POST
def kind_add(request):
    kind, error = services.add_custom_kind(request.user, request.POST.get('name'))
    if error:
        return JsonResponse({'error': error}, status=400)
    return JsonResponse({
        'id': kind.pk,
        'name': kind.name,
        'delete_url': reverse('property_kind_delete', args=[kind.pk]),
    })


@login_required
@require_POST
def kind_delete(request, pk):
    get_object_or_404(PropertyKind, pk=pk, owner=request.user).delete()
    return HttpResponse(status=204)


@login_required
def property_create(request):
    return _property_form(request)


def _own_property(request, pk):
    return get_object_or_404(Property, pk=pk, owner=request.user)


@login_required
def property_detail(request, pk):
    property_obj = _own_property(request, pk)
    if request.headers.get('X-Modal'):
        # «Посмотреть» from the card menu: a summary card in the modal window.
        return render(request, 'properties/_summary.html', {
            'property': property_obj,
            'tenants': property_obj.tenants.all(),
        })
    month = services.parse_month(request.GET.get('month'))
    return render(request, 'properties/detail.html', object_page_context(request, property_obj, month))


def object_page_context(request, property_obj, month):
    """The object page: object info, the month's input and the selected payer's bill."""
    bill = billing_services.month_bill(property_obj, month)
    try:
        selected = int(request.GET.get('tenant', ''))
    except ValueError:
        selected = None  # not chosen: the first tenant
    owner_shown = bool(bill.owner.lines) or property_obj.is_owner_used or not bill.payers
    if not bill.payer_for(selected) and not (selected == 0 and owner_shown):
        selected = bill.payers[0].tenant.pk if bill.payers else 0
    occupied = sum((t.share_percent or 0 for t in property_obj.tenants.all()), 0)
    return {
        'property': property_obj,
        'bill': bill,
        'selected_tenant': selected,
        'free_percent': max(100 - occupied, 0),
        'missing_kinds': [(kind, kind.label) for kind in billing_services.missing_kinds(property_obj)],
        'month': services.month_param(month),
        'month_label': services.month_label(month),
        'month_name': services.MONTH_NAMES[month.month - 1].lower(),
        'prev_month': services.month_param(services.shift_month(month, -1)),
        'next_month': services.month_param(services.shift_month(month, 1)),
    }


@login_required
def property_edit(request, pk):
    return _property_form(request, _own_property(request, pk))


@login_required
def property_delete(request, pk):
    property_obj = _own_property(request, pk)
    is_modal = bool(request.headers.get('X-Modal'))
    if request.method == 'POST':
        name = property_obj.name
        property_obj.delete()
        messages.success(request, f'Объект «{name}» удалён.')
        url = reverse('property_list')
        if is_modal:
            return HttpResponse(status=204, headers={'X-Modal-Redirect': url})
        return redirect(url)
    # In the modal: a small confirmation window; otherwise the full page.
    template = 'properties/_delete.html' if is_modal else 'properties/delete.html'
    return render(request, template, {
        'property': property_obj,
        'tenant_count': property_obj.tenants.count(),
    })


@login_required
def property_tenants(request, pk):
    """«+ Добавить арендатора» / «Изменить арендаторов» on the card: only the tenants, in the modal."""
    property_obj = get_object_or_404(Property, pk=pk, owner=request.user)
    is_modal = request.headers.get('X-Modal') == '1'
    data = request.POST if request.method == 'POST' else None
    unit = (data or {}).get('share_unit') or property_obj.share_unit
    if unit not in Property.ShareUnit.values:
        unit = Property.ShareUnit.PERCENT
    formset = TenantFormSet(data, instance=property_obj, prefix='tenants', form_kwargs={'share_unit': unit})
    if property_obj.tenants.exists():
        formset.extra = 0

    if data is not None:
        formset.share_unit = unit
        formset.total_area = property_obj.area
        if formset.is_valid():
            services.save_tenants(property_obj, formset, unit)
            messages.success(request, f'Арендаторы «{property_obj.name}» сохранены.')
            url = reverse('property_list')
            if is_modal:
                return HttpResponse(status=204, headers={'X-Modal-Redirect': modal_back_url(request) or url})
            return redirect(url)

    template = 'properties/_tenants_form.html' if is_modal else 'properties/tenants_form.html'
    return render(request, template, {'property': property_obj, 'formset': formset, 'share_unit': unit})
