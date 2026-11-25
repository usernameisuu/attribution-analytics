"""Compare a selected metric against a user-provided threshold.

This is an on-demand comparison, not a scheduled anomaly detector.
"""
from decimal import Decimal

from .attribution import number, calculation_precision
from .exploration import profit, select_rows, totals, validate_scope


@calculation_precision
def compare(scenario, rows, scope, threshold):
    threshold = number(threshold)
    if threshold <= 0 or threshold > Decimal('10000'):
        raise ValueError('阈值必须大于 0 且不超过 10000')
    if scenario not in {'ecommerce', 'consumer'}:
        raise ValueError('未知业务线')
    scope = validate_scope(scope, rows)
    selected = {period: select_rows(rows, scope, period) for period in ('baseline', 'current')}
    if any(not items for items in selected.values()):
        raise ValueError('筛选后没有可比较数据')
    values = {period: totals(items) for period, items in selected.items()}
    result = {'scope': scope, 'threshold': str(threshold), 'status': 'not_applicable',
              'baseline': None, 'current': None, 'delta': None, 'change': None, 'reason': None}
    if scenario == 'ecommerce':
        baseline, current = (values[p]['revenue'] for p in ('baseline', 'current'))
        result.update(metric='GMV', unit='元', threshold_unit='%',
                      method='两期 GMV 总额相对变化率的绝对值达到阈值即标记',
                      baseline=str(baseline), current=str(current), delta=str(current-baseline))
        if not baseline:
            result['reason'] = '基期 GMV 为零，相对变化率无法计算。'
            return result
        change = (current-baseline) / baseline * 100
    else:
        result.update(metric='样例净利润率', unit='%', threshold_unit='百分点',
                      method='两期净利润率变化百分点的绝对值达到阈值即标记')
        if any(not values[p]['revenue'] for p in values):
            result['reason'] = '基期或现期营收为零，净利润率无法计算。'
            return result
        baseline, current = (profit(values[p]) / values[p]['revenue'] * 100 for p in ('baseline', 'current'))
        change = current-baseline
        result.update(baseline=str(baseline), current=str(current), delta=str(change))
    result['change'] = str(change)
    result['status'] = 'anomaly' if abs(change) >= threshold else 'normal'
    return result
