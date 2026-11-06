from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.tenants.forms import TenantFormSet

from . import services
from .forms import PropertyForm
from .models import Property, PropertyKind


@login_required
def property_list(request):
    month = services.parse_month(request.GET.get('month'))
    properties = Property.objects.filter(owner=request.user).prefetch_related('tenants')

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
    """Create or edit an object with its tenants. Renders bare content when opened in the modal."""
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
    if property_obj and property_obj.tenants.exists():
        formset.extra = 0

    if data is not None:
        form_ok = form.is_valid()
        formset.share_unit = unit
        formset.total_area = form.cleaned_data.get('area')
        owner_used = data.get('occupancy') == Property.Occupancy.OWNER
        tenants_ok = owner_used or formset.is_valid()
        if form_ok and tenants_ok:
            saved = services.save_property(form, formset, request.user)
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
    return render(request, 'properties/detail.html', {'property': property_obj})


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
