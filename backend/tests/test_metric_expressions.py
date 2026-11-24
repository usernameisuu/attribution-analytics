import unittest
from decimal import Decimal
from app.domain.metric_expressions import evaluate


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
