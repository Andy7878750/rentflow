from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .forms import PropertyForm
from .models import Property


@login_required
def property_list(request):
    if request.method == 'POST':
        form = PropertyForm(request.POST)
        if form.is_valid():
            property_obj = form.save(commit=False)
            property_obj.owner = request.user
            property_obj.save()
            return redirect('property_list')
    else:
        form = PropertyForm()

    properties = Property.objects.filter(owner=request.user)
    return render(request, 'properties/list.html', {'form': form, 'properties': properties})
