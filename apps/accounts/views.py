from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.properties.models import Property

from .utils import user_display


@login_required
def home(request):
    full_name = user_display(request.user)
    has_properties = Property.objects.filter(owner=request.user).exists()
    return render(request, 'dashboard.html', {'full_name': full_name, 'has_properties': has_properties})


def privacy(request):
    return render(request, 'legal/privacy.html')
