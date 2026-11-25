"""Versioned built-in metric definitions for the current sample scenarios.

These definitions document the sample's arithmetic, not confirmed accounting
policy or an editable, persisted metric dictionary.
"""
from copy import deepcopy

from .metric_expressions import validate_definitions

VERSION = 'sample-metrics-v1'


def _ref(name):
    return {'ref': name}


def _op(op, left, right):
    return {'op': op, 'args': [left, right]}


_MONEY = {'cny': 1}
_DEFINITIONS = {
    'sales_amount': {'unit': _MONEY, 'expression': None},
    'material_cost': {'unit': _MONEY, 'expression': None},
    'logistics_cost': {'unit': _MONEY, 'expression': None},
    'commission_cost': {'unit': _MONEY, 'expression': None},
    'other_cost': {'unit': _MONEY, 'expression': None},
    'tax_cost': {'unit': _MONEY, 'expression': None},
    'visits': {'unit': {'visit': 1}, 'expression': None},
    'orders': {'unit': {'order': 1}, 'expression': None},
    'conversion_factor': {'unit': {'order': 1, 'visit': -1},
                          'expression': _op('div', _ref('orders'), _ref('visits'))},
    'basket': {'unit': {'cny': 1, 'order': -1},
               'expression': _op('div', _ref('sales_amount'), _ref('orders'))},
    'gmv_from_factors': {'unit': _MONEY,
                         'expression': _op('mul', _op('mul', _ref('visits'), _ref('conversion_factor')), _ref('basket'))},
    'sample_net_profit': {'unit': _MONEY, 'expression': _op('sub', _op('sub', _op('sub',
                          _op('sub', _op('sub', _ref('sales_amount'), _ref('material_cost')),
                              _ref('logistics_cost')), _ref('commission_cost')), _ref('other_cost')), _ref('tax_cost'))},
    'sample_net_margin': {'unit': {}, 'expression': _op('div', _ref('sample_net_profit'), _ref('sales_amount'))},
}

_SCENARIOS = {
    'ecommerce': {
        'metric': 'gmv_from_factors', 'name': 'GMV',
        'description': '样例中以营收字段作为 GMV；访问次数 × 订单数/访问次数 × 营收/订单数。',
        'limitations': ['访问次数不是去重访客；订单与访问的比值是样例因子。', '订单或访问为零时乘法因子不适用。'],
    },
    'consumer': {
        'metric': 'sample_net_profit', 'margin_metric': 'sample_net_margin', 'name': '样例净利润',
        'description': '营收减原材料、物流、佣金、其他成本与税费；利润率等于利润除以营收。',
        'limitations': ['成本与税费的财务归类尚未确认；营收为零时利润率不适用。'],
    },
}


def catalog(scenario):
    if scenario not in _SCENARIOS:
        raise ValueError('未知业务线')
    validate_definitions(_DEFINITIONS)
    return deepcopy({'version': VERSION, 'scenario': scenario, 'scenario_metric': _SCENARIOS[scenario],
                     'definitions': _DEFINITIONS})
