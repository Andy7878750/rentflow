from decimal import Decimal

from django.test import SimpleTestCase

from . import services
from .models import Tenant


class ShareConversionTests(SimpleTestCase):
    def test_percent_from_area(self):
        self.assertEqual(services.percent_from_area(Decimal('27'), Decimal('60')), Decimal('45.00'))
        self.assertEqual(services.percent_from_area(Decimal('20'), Decimal('60')), Decimal('33.33'))

    def test_area_from_percent(self):
        self.assertEqual(services.area_from_percent(Decimal('45'), Decimal('60')), Decimal('27.00'))

    def test_unknown_object_area_gives_none(self):
        self.assertIsNone(services.percent_from_area(Decimal('27'), None))
        self.assertIsNone(services.area_from_percent(Decimal('45'), Decimal('0')))

    def test_apply_share_fills_other_unit(self):
        tenant = Tenant()
        services.apply_share(tenant, Decimal('30'), 'area', Decimal('60'))
        self.assertEqual((tenant.area, tenant.share_percent), (Decimal('30'), Decimal('50.00')))

        services.apply_share(tenant, Decimal('25'), 'percent', None)
        self.assertEqual((tenant.share_percent, tenant.area), (Decimal('25'), None))


class PlainNumberTests(SimpleTestCase):
    def test_round_numbers_stay_readable(self):
        self.assertEqual(str(services.plain(Decimal('60.00'))), '60')
        self.assertEqual(str(services.plain(Decimal('27.50'))), '27.5')
        self.assertEqual(services.fmt(Decimal('100.00')), '100')


class ShareValidationTests(SimpleTestCase):
    def test_percent_up_to_100_is_fine(self):
        self.assertIsNone(services.share_error([Decimal('45'), Decimal('55')], 'percent', None))

    def test_percent_over_100(self):
        error = services.share_error([Decimal('60'), Decimal('50.5')], 'percent', None)
        self.assertEqual(error, 'Сумма долей 110,5% — больше 100%.')

    def test_area_needs_object_area(self):
        self.assertIn('площадь объекта', services.share_error([Decimal('10')], 'area', None))

    def test_area_over_object_area(self):
        error = services.share_error([Decimal('40'), Decimal('30')], 'area', Decimal('60'))
        self.assertEqual(error, 'Арендаторы занимают 70 м² — больше площади объекта (60 м²).')
