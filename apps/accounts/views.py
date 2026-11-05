from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render


@login_required
def home(request):
    return redirect('property_list')


def privacy(request):
    return render(request, 'legal/privacy.html')
