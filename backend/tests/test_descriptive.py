import unittest
from decimal import Decimal

from app.domain.descriptive import observations


class DescriptiveTests(unittest.TestCase):
    def test_missing_period_is_not_treated_as_zero(self):
        selected = {
            'baseline': [{'channel': 'A', 'visitors': '0'}, {'channel': 'B', 'visitors': '5'}],
            'current': [{'channel': 'A', 'visitors': '4'}, {'channel': 'C', 'visitors': '9'}],
        }
        evidence = observations([{'factor_key': 'visitors', 'limitations': []}], selected)[0]['evidence'][0]
        groups = {group['value']: group for group in evidence['groups']}
        self.assertEqual(groups['A']['baseline'], '0')
        self.assertEqual(groups['A']['delta'], '4')
        self.assertIsNone(groups['B']['current'])
        self.assertIsNone(groups['B']['delta'])
        self.assertIsNone(groups['C']['baseline'])
        self.assertIsNone(groups['C']['delta'])
        self.assertIn('没有记录', evidence['note'])

    def test_ratio_uses_totals_instead_of_average_of_row_ratios(self):
        selected = {
            'baseline': [{'channel':'A','orders':'100','visitors':'100'}, {'channel':'A','orders':'0','visitors':'900'}],
            'current': [{'channel':'A','orders':'200','visitors':'1000'}],
        }
        item = {'factor_key':'conversion','limitations':[]}
        evidence = observations([item],selected)[0]['evidence'][0]
        group = evidence['groups'][0]
        self.assertEqual(Decimal(group['baseline']), Decimal('0.1'))
        self.assertEqual(Decimal(group['current']), Decimal('0.2'))
        self.assertEqual(Decimal(group['delta']), Decimal('0.1'))

    def test_group_limit_is_explicit_and_uncomputable_sorted_last(self):
        selected = {period: [] for period in ('baseline','current')}
        for index in range(21):
            selected['baseline'].append({'channel':str(index), 'orders':'1', 'visitors':'10'})
            selected['current'].append({'channel':str(index), 'orders':str(index), 'visitors':'10'})
        selected['current'][0]['visitors']='0'
        item = {'factor_key':'conversion','limitations':[]}
        evidence=observations([item],selected)[0]['evidence'][0]
        self.assertEqual(evidence['total_groups'],21)
        self.assertTrue(evidence['truncated'])
        self.assertEqual(len(evidence['groups']),20)
        self.assertNotIn('0',[group['value'] for group in evidence['groups']])
