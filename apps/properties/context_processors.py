from apps.billing.models import Meter, Receipt

from .models import Property


def sidebar(request):
    """Properties listed in the app sidebar, and how many services they have, for the signed-in landlord."""
    if not request.user.is_authenticated:
        return {}
    return {
        'sidebar_properties': Property.objects.filter(owner=request.user).only('id', 'name'),
        'sidebar_receipt_count': Receipt.objects.filter(property__owner=request.user).count,
        'sidebar_meter_count': Meter.objects.filter(property__owner=request.user).count,
    }
