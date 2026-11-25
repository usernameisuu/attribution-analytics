import copy
import unittest
from decimal import Decimal

from app.domain.monitoring import compare
from test_exploration import SCOPE, facts


class MonitoringTests(unittest.TestCase):
    def test_gmv_relative_threshold_is_inclusive(self):
        outcome = compare('ecommerce', facts(), SCOPE, '28')
        self.assertEqual(outcome['baseline'], '4000')
        self.assertEqual(outcome['current'], '2880')
        self.assertEqual(Decimal(outcome['change']), Decimal('-28'))
        self.assertEqual(outcome['status'], 'anomaly')
        self.assertEqual(compare('ecommerce', facts(), SCOPE, '28.1')['status'], 'normal')

    def test_consumer_uses_percentage_points_not_relative_change(self):
        outcome = compare('consumer', facts(), SCOPE, '28')
        self.assertEqual(Decimal(outcome['baseline']), Decimal('27'))
        self.assertLess(Decimal(outcome['current']), 0)
        self.assertEqual(outcome['threshold_unit'], '百分点')
        self.assertEqual(outcome['status'], 'anomaly')

    def test_zero_denominators_not_classified(self):
        rows = copy.deepcopy(facts())
        for row in rows:
            if row['date'] <= '2026-10-02':
                row['revenue'] = row['orders'] = row['visitors'] = '0'
        for scenario in ('ecommerce', 'consumer'):
            with self.subTest(scenario=scenario):
                result = compare(scenario, rows, SCOPE, '10')
                self.assertEqual(result['status'], 'not_applicable')
                self.assertIsNone(result['change'])
                self.assertIn('为零', result['reason'])

    def test_invalid_threshold_and_scope_are_rejected(self):
        for threshold in ('0', '-1', 'NaN', 'Infinity', '10001'):
            with self.subTest(threshold=threshold), self.assertRaises(ValueError):
                compare('ecommerce', facts(), SCOPE, threshold)
        with self.assertRaises(ValueError):
            compare('ecommerce', facts(), {}, '10')
