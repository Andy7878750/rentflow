from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from .models import Requisites


@login_required
def home(request):
    return redirect('property_list')


def privacy(request):
    return render(request, 'legal/privacy.html')


# what is typed in «Ваши реквизиты»: field → (digits only, the lengths allowed, the message)
DIGITS = {
    'inn': ((10, 12), 'ИНН — 10 цифр у организации, 12 — у ИП.'),
    'ogrn': ((13, 15), 'ОГРН — 13 цифр, ОГРНИП — 15.'),
    'kpp': ((9,), 'КПП — 9 цифр.'),
    'account': ((20,), 'Расчётный счёт — 20 цифр.'),
    'bik': ((9,), 'БИК — 9 цифр.'),
    'corr_account': ((20,), 'Корр. счёт — 20 цифр.'),
}
TEXTS = ('legal_name', 'address', 'phone', 'email', 'bank')


@login_required
def requisites(request):
    """«Ваши реквизиты» (2026-11-25): a small window — who issues the bills and where to pay. Typed once; they go to
    every bill «с реквизитами». Opened from the name in the top bar and from «Настроить счёт»."""
    from apps.properties.views import modal_back_url

    obj, _ = Requisites.objects.get_or_create(user=request.user)
    errors, data = {}, None
    if request.method == 'POST':
        data = request.POST
        for name in TEXTS:
            setattr(obj, name, data.get(name, '').strip()[:Requisites._meta.get_field(name).max_length])
        for name, (lengths, message) in DIGITS.items():
            value = ''.join(ch for ch in data.get(name, '') if ch.isdigit())
            if value and len(value) not in lengths:
                errors[name] = message
            setattr(obj, name, value)
        if obj.email and '@' not in obj.email:
            errors['email'] = 'Почта — с «@».'
        if not errors:
            obj.save()
            messages.success(request, 'Реквизиты сохранены.')
            url = modal_back_url(request) or reverse('property_list')
            if request.headers.get('X-Modal'):
                return HttpResponse(status=204, headers={'X-Modal-Redirect': url})
            return redirect(url)
    return render(request, 'accounts/_requisites.html', {'req': obj, 'errors': errors})
