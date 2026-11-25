import unittest
from decimal import Decimal
from app.domain.metric_expressions import evaluate, validate_definitions
from app.domain.metric_catalog import catalog


def ref(name): return {'ref': name}
def op(kind, a, b): return {'op': kind, 'args': [a, b]}


class MetricExpressionTests(unittest.TestCase):
    def setUp(self):
        self.definitions = {
            'revenue': {'unit': {'cny': 1}, 'expression': None},
            'cost': {'unit': {'cny': 1}, 'expression': None},
            'orders': {'unit': {'order': 1}, 'expression': None},
            'profit': {'unit': {'cny': 1}, 'expression': op('sub', ref('revenue'), ref('cost'))},
            'margin': {'unit': {}, 'expression': op('div', ref('profit'), ref('revenue'))},
            'basket': {'unit': {'cny': 1, 'order': -1}, 'expression': op('div', ref('revenue'), ref('orders'))},
        }
        self.inputs = {'revenue': '100', 'cost': '60', 'orders': '4'}

    def test_derived_metrics_and_units(self):
        self.assertEqual(evaluate(self.definitions, self.inputs, 'margin'), {'value': Decimal('.4'), 'unit': {}})
        self.assertEqual(evaluate(self.definitions, self.inputs, 'basket')['value'], Decimal(25))

    def test_invalid_cycle_units_zero_and_unknown_are_rejected(self):
        cases = [({'x': {'unit': {}, 'expression': ref('x')}}, {}, 'x'),
                 ({'x': {'unit': {}, 'expression': ref('missing')}}, {}, 'x'),
                 ({**self.definitions, 'x': {'unit': {}, 'expression': op('add', ref('revenue'), ref('orders'))}}, self.inputs, 'x'),
                 (self.definitions, {**self.inputs, 'revenue': '0'}, 'margin'),
                 ({'x': {'unit': {}, 'expression': {'python': '1+1'}}}, {}, 'x')]
        for definitions, inputs, target in cases:
            with self.subTest(target=target, definitions=definitions), self.assertRaises(ValueError):
                evaluate(definitions, inputs, target)

    def test_validate_every_definition_without_requiring_values(self):
        self.assertEqual(validate_definitions(self.definitions)['margin'], {})
        bad = {**self.definitions, 'orphan': {'unit': {}, 'expression': ref('missing')}}
        with self.assertRaisesRegex(ValueError, 'unknown metric'):
            validate_definitions(bad)
        bad = {**self.definitions, 'orphan': {'unit': {}, 'expression': ref('orphan')}}
        with self.assertRaisesRegex(ValueError, 'cycle'):
            validate_definitions(bad)
        bad = {**self.definitions, 'orphan': {'unit': {}, 'expression': ref('revenue')}}
        with self.assertRaisesRegex(ValueError, 'unit'):
            validate_definitions(bad)

    def test_builtin_formulas_match_hand_calculated_examples(self):
        definitions = catalog('ecommerce')['definitions']
        inputs = {'visits': '100000', 'orders': '5000', 'sales_amount': '1000000',
                  'material_cost': '500000', 'logistics_cost': '100000',
                  'commission_cost': '50000', 'other_cost': '100000', 'tax_cost': '0'}
        self.assertEqual(evaluate(definitions, inputs, 'gmv_from_factors')['value'], Decimal('1000000'))
        self.assertEqual(evaluate(definitions, inputs, 'sample_net_profit')['value'], Decimal('250000'))
        self.assertEqual(evaluate(definitions, inputs, 'sample_net_margin')['value'], Decimal('.25'))
        self.assertEqual(catalog('consumer')['version'], catalog('ecommerce')['version'])
        definitions['sales_amount']['unit']['cny'] = 99
        self.assertEqual(catalog('ecommerce')['definitions']['sales_amount']['unit']['cny'], 1)

    def test_static_validation_does_not_pretend_zero_denominators_are_valid(self):
        definitions = catalog('ecommerce')['definitions']
        validate_definitions(definitions)
        with self.assertRaisesRegex(ValueError, 'division by zero'):
            evaluate(definitions, {'visits': '0', 'orders': '0', 'sales_amount': '0'}, 'gmv_from_factors')
