"""One rule for every e-mail field of the site (2026-11-25): the tenant's, the management company's, the landlord's
requisites, sign-up, change of e-mail. The same phrases as static/js/fields.js (`emailProblem`)."""
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

EMAIL_BAD = 'Введите правильный адрес электронной почты.'
EMAIL_LATIN = 'До «@» — только латинские буквы и цифры.'


def email_problem(value):
    """'' when the address is right (or empty), otherwise the phrase to show under the field."""
    value = (value or '').strip()
    if not value:
        return ''
    try:
        validate_email(value)
    except ValidationError:
        at = value.find('@')
        if at > 0 and not value[:at].isascii():
            return EMAIL_LATIN
        return EMAIL_BAD
    return ''


def check_email(value):
    problem = email_problem(value)
    if problem:
        raise ValidationError(problem, code='invalid')


def use_email_rule(form, *names):
    """Our rule instead of Django's own for these e-mail fields of a form."""
    for name in names:
        if name in form.fields:
            form.fields[name].validators = [check_email]
