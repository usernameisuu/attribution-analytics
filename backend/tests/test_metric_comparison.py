import unittest
from copy import deepcopy
from decimal import Decimal

from app.domain.metric_catalog import catalog
from app.domain.metric_comparison import compare_synthetic


class MetricComparisonTests(unittest.TestCase):
    def test_builtin_formulas_agree_on_both_scenarios_and_margin(self):
        for scenario,target in [('ecommerce','gmv_from_factors'),
                                ('consumer','sample_net_profit'),('consumer','sample_net_margin')]:
            with self.subTest(scenario=scenario,target=target):
                result=compare_synthetic(scenario,catalog(scenario)['definitions'],target)
                self.assertEqual(result['dataset_version'],'synthetic-daily-seed-41')
                self.assertEqual(len(result['data_digest']),64)
                self.assertTrue(all(abs(Decimal(item['difference'])) < Decimal('1e-25') for item in result['periods']))
                self.assertIn('不证明',result['notice'])

    def test_changed_formula_reveals_the_expected_difference(self):
        definitions=deepcopy(catalog('ecommerce')['definitions'])
        root=definitions['gmv_from_factors']
        root['expression']={'op':'mul','args':[root['expression'],{'const':'0.9'}]}
        result=compare_synthetic('ecommerce',definitions,'gmv_from_factors')
        for period in result['periods']:
            self.assertLess(abs(Decimal(period['difference'])+Decimal(period['builtin'])*Decimal('0.1')),Decimal('1e-25'))

    def test_unsupported_target_and_missing_synthetic_input_fail(self):
        definitions=deepcopy(catalog('ecommerce')['definitions'])
        with self.assertRaisesRegex(ValueError,'根指标'):
            compare_synthetic('ecommerce',definitions,'sample_net_profit')
        definitions['other_sales']={'unit':{'cny':1},'expression':None}
        definitions['gmv_from_factors']['expression']={'ref':'other_sales'}
        with self.assertRaisesRegex(ValueError,'未提供所需原子指标'):
            compare_synthetic('ecommerce',definitions,'gmv_from_factors')

    def test_only_referenced_atoms_are_bound_and_units_must_match(self):
        definitions=deepcopy(catalog('ecommerce')['definitions'])
        definitions['visits']['unit']={'cny':1}
        definitions['gmv_from_factors']['expression']={'ref':'visits'}
        # Remove the old derived factor whose units depend on the changed visit unit.
        definitions.pop('conversion_factor')
        with self.assertRaisesRegex(ValueError,'原子指标单位不匹配'):
            compare_synthetic('ecommerce',definitions,'gmv_from_factors')
        definitions['gmv_from_factors']['expression']={'ref':'sales_amount'}
        result=compare_synthetic('ecommerce',definitions,'gmv_from_factors')
        self.assertTrue(all(Decimal(item['difference']) == 0 for item in result['periods']))
