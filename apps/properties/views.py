from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from . import services
from .forms import PropertyForm
from .models import Property


@login_required
def property_list(request):
    month = services.parse_month(request.GET.get('month'))
    properties = Property.objects.filter(owner=request.user)

    # Tenants, readings and invoices don't exist yet: zero placeholders until billing lands.
    summary = {
        'to_invoice': Decimal('0.00'),
        'tenants': 0,
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


@login_required
def property_create(request):
    if request.method == 'POST':
        form = PropertyForm(request.POST)
        if form.is_valid():
            property_obj = form.save(commit=False)
            property_obj.owner = request.user
            property_obj.save()
            return redirect('property_list')
    else:
        form = PropertyForm()
    return render(request, 'properties/form.html', {'form': form})


def _own_property(request, pk):
    return get_object_or_404(Property, pk=pk, owner=request.user)


@login_required
def property_detail(request, pk):
    return render(request, 'properties/detail.html', {'property': _own_property(request, pk)})


@login_required
def property_edit(request, pk):
    property_obj = _own_property(request, pk)
    form = PropertyForm(request.POST or None, instance=property_obj)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('property_detail', pk=property_obj.pk)
    return render(request, 'properties/form.html', {'form': form, 'property': property_obj})


@login_required
def property_delete(request, pk):
    property_obj = _own_property(request, pk)
    if request.method == 'POST':
        property_obj.delete()
        return redirect('property_list')
    return render(request, 'properties/delete.html', {'property': property_obj})
