"""Compare a draft formula with the current engine on fixed synthetic data.

This provides examples, not proof of semantic or algorithmic equivalence.
"""
from decimal import Decimal, localcontext

from .datasets import generate, normalize
from .exploration import analyze, default_scope, select_rows, totals
from .metric_catalog import catalog
from .metric_expressions import evaluate, validate_definitions

_INPUTS = {'visits':'visitors', 'orders':'orders', 'sales_amount':'revenue',
           'material_cost':'material', 'logistics_cost':'logistics',
           'commission_cost':'commission', 'other_cost':'other', 'tax_cost':'tax'}
_DATASET_VERSION = 'synthetic-daily-seed-41'


def _required_inputs(definitions, target):
    """Find only the atomic inputs actually used by the requested metric."""
    visited, required = set(), set()
    def visit_metric(name):
        if name in visited:
            return
        visited.add(name)
        expression = definitions[name]['expression']
        if expression is None:
            required.add(name)
        else:
            visit_expression(expression)
    def visit_expression(expression):
        if 'ref' in expression:
            visit_metric(expression['ref'])
        elif 'op' in expression:
            for child in expression['args']:
                visit_expression(child)
    visit_metric(target)
    return required


def compare_synthetic(scenario, definitions, target):
    meta = catalog(scenario)
    targets = [meta['scenario_metric']['metric']]
    if meta['scenario_metric'].get('margin_metric'):
        targets.append(meta['scenario_metric']['margin_metric'])
    if target not in targets:
        raise ValueError('仅支持比较当前业务场景的根指标')
    validate_definitions(definitions)
    if target not in definitions:
        raise ValueError('合成数据比较缺少目标指标')
    required = _required_inputs(definitions, target)
    if required - set(_INPUTS):
        raise ValueError('合成数据未提供所需原子指标')
    for name in required:
        actual = {key:value for key,value in definitions[name]['unit'].items() if value}
        expected = meta['definitions'][name]['unit']
        if actual != expected:
            raise ValueError('合成数据原子指标单位不匹配')
    rows, digest = normalize(generate(scenario, seed=41))
    scope = default_scope(rows)
    snapshot = analyze(scenario, rows, scope, _DATASET_VERSION)
    margin = target == meta['scenario_metric'].get('margin_metric')
    breakdown = snapshot['margin_breakdown'] if margin else snapshot['breakdown']
    output = []
    with localcontext() as context:
        context.prec = 80
        for period in ('baseline', 'current'):
            aggregate = totals(select_rows(rows, scope, period))
            inputs = {name:str(aggregate[_INPUTS[name]]) for name in required}
            evaluated = evaluate(definitions, inputs, target)
            builtin = Decimal(breakdown[period]) / (100 if margin else 1)
            output.append({'period':period, 'draft':str(evaluated['value']), 'builtin':str(builtin),
                           'difference':str(evaluated['value']-builtin)})
    return {'target':target, 'unit':meta['definitions'][target]['unit'], 'periods':output,
            'dataset_version':_DATASET_VERSION, 'data_digest':digest, 'scope':scope,
            'builtin_metric_version':meta['version'], 'builtin_algorithm_version':snapshot['algorithm_version'],
            'notice':'仅比较一组合成数据，不证明公式在其他数据下等价，也不启用草稿。利润率以小数而非百分数表示；草稿计算为 Decimal 38 位，差异可能包含舍入误差。'}
