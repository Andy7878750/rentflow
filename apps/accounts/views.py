from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def home(request):
    profile = getattr(request.user, 'profile', None)
    full_name = (profile.full_name if profile else '') or request.user.email
    return render(request, 'dashboard.html', {'full_name': full_name})
