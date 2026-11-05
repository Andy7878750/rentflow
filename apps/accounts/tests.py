from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from .models import Profile

User = get_user_model()

SIGNUP_DATA = {
    'full_name': 'Андрей',
    'email': 'landlord@example.ru',
    'password1': 'secret1',
    'privacy_consent': 'on',
}


def make_verified_user(email='landlord@example.ru', password='secret1', full_name='Андрей'):
    user = User.objects.create_user(username=email, email=email, password=password)
    Profile.objects.create(user=user, full_name=full_name, privacy_consent_at='2026-01-01T00:00Z')
    EmailAddress.objects.create(user=user, email=email, verified=True, primary=True)
    return user


class SignupTests(TestCase):
    def setUp(self):
        # allauth keeps its rate limits (e.g. one confirmation email per address) in the cache.
        cache.clear()

    def test_signup_creates_profile_and_sends_russian_email(self):
        # allauth sends the confirmation email after the transaction commits.
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('account_signup'), SIGNUP_DATA)

        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email=SIGNUP_DATA['email'])
        self.assertEqual(user.profile.full_name, 'Андрей')
        self.assertIsNotNone(user.profile.privacy_consent_at)

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertTrue(message.subject.startswith('[RentFlow]'))
        self.assertIn('подтвер', message.subject.lower())
        self.assertIn('Андрей', message.body)
        self.assertNotIn('example.com', message.body)

    def test_consent_is_required(self):
        data = {**SIGNUP_DATA, 'privacy_consent': ''}
        response = self.client.post(reverse('account_signup'), data)

        self.assertEqual(response.status_code, 200)
        self.assertIn('privacy_consent', response.context['form'].errors)
        self.assertFalse(User.objects.exists())

    def test_password_minimum_is_six_characters(self):
        short = self.client.post(reverse('account_signup'), {**SIGNUP_DATA, 'password1': '12345'})
        self.assertIn('password1', short.context['form'].errors)
        self.assertIn('6', short.context['form'].errors['password1'][0])
        self.assertFalse(User.objects.exists())

        ok = self.client.post(reverse('account_signup'), {**SIGNUP_DATA, 'password1': '123456'})
        self.assertEqual(ok.status_code, 302)
        self.assertTrue(User.objects.filter(email=SIGNUP_DATA['email']).exists())

    def test_errors_are_in_russian(self):
        response = self.client.post(reverse('account_signup'), {**SIGNUP_DATA, 'password1': '1'})
        self.assertIn('пароль', response.context['form'].errors['password1'][0].lower())

    def test_signup_page_links_to_privacy_policy(self):
        response = self.client.get(reverse('account_signup'))
        self.assertContains(response, reverse('privacy'))


class LoginTests(TestCase):
    def test_verified_user_can_log_in(self):
        make_verified_user()
        response = self.client.post(
            reverse('account_login'),
            {'login': 'landlord@example.ru', 'password': 'secret1'},
        )
        self.assertRedirects(response, reverse('home'), fetch_redirect_response=False)

    def test_wrong_password_is_rejected(self):
        make_verified_user()
        response = self.client.post(
            reverse('account_login'),
            {'login': 'landlord@example.ru', 'password': 'wrong-password'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['user'].is_authenticated)

    def test_unverified_user_cannot_log_in(self):
        user = make_verified_user()
        EmailAddress.objects.filter(user=user).update(verified=False)
        self.client.post(
            reverse('account_login'),
            {'login': 'landlord@example.ru', 'password': 'secret1'},
        )
        self.assertNotIn('_auth_user_id', self.client.session)


class AccountPagesTests(TestCase):
    def test_privacy_page_is_public(self):
        response = self.client.get(reverse('privacy'))
        self.assertEqual(response.status_code, 200)

    def test_settings_pages_require_login(self):
        for name in ('account_change_password', 'account_email'):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302, name)
            self.assertIn(reverse('account_login'), response['Location'])

    def test_settings_pages_render_for_logged_in_user(self):
        user = make_verified_user()
        self.client.force_login(user)
        for name in ('account_change_password', 'account_email'):
            response = self.client.get(reverse(name))
            self.assertContains(response, 'Настройки аккаунта', msg_prefix=name)

    def test_password_change(self):
        user = make_verified_user()
        self.client.force_login(user)
        response = self.client.post(
            reverse('account_change_password'),
            {'oldpassword': 'secret1', 'password1': 'newsecret', 'password2': 'newsecret'},
        )
        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertTrue(user.check_password('newsecret'))
