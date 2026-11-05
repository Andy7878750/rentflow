from .models import Property


def sidebar(request):
    """Properties listed in the app sidebar for the signed-in landlord."""
    if not request.user.is_authenticated:
        return {}
    return {'sidebar_properties': Property.objects.filter(owner=request.user).only('id', 'name')}
