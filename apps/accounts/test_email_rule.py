from django.test import SimpleTestCase

from apps.accounts.forms import CustomSignupForm
from apps.properties.forms import PropertyForm
from apps.tenants.forms import TenantForm
from config.validators import EMAIL_BAD, EMAIL_LATIN, email_problem


class EmailRuleTests(SimpleTestCase):
    """One e-mail rule for the whole site (2026-11-25): the same phrases in every form."""

    def test_problem(self):
        self.assertEqual(email_problem(''), '')
        self.assertEqual(email_problem('a@mail.ru'), '')
        self.assertEqual(email_problem('a@mail'), EMAIL_BAD)
        self.assertEqual(email_problem('amail.ru'), EMAIL_BAD)
        self.assertEqual(email_problem('андрей@mail.ru'), EMAIL_LATIN)

    def test_every_form_uses_it(self):
        for form, name in ((PropertyForm(), 'management_email'), (TenantForm(), 'email'), (CustomSignupForm(), 'email')):
            with self.subTest(form=type(form).__name__):
                field = form.fields[name]
                self.assertEqual(field.validators[0].__name__, 'check_email')
                with self.assertRaisesMessage(Exception, EMAIL_LATIN):
                    field.clean('андрей@mail.ru')
