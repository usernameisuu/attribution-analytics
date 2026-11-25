"""Descriptive baseline daily variability, not a forecast or causal estimate."""
from decimal import Decimal
from datetime import date

from .attribution import calculation_precision
from .exploration import group_totals, profit, select_rows, validate_scope
from .scenarios import SCENARIOS


@calculation_precision
def baseline_variability(scenario, rows, scope):
    if scenario not in SCENARIOS:
        raise ValueError('未知业务线')
    scope = validate_scope(scope, rows)
    daily = group_totals(select_rows(rows, scope, 'baseline'), 'date')
    if not daily:
        raise ValueError('基期筛选范围没有数据')
    expected_days = (date.fromisoformat(scope['baseline'][1])-date.fromisoformat(scope['baseline'][0])).days + 1
    samples = {key:[] for key in SCENARIOS[scenario]['current']}
    metric_samples = []
    for _, values in sorted(daily.items()):
        if scenario == 'ecommerce':
            day = {'visitors':values['visitors'],
                   'conversion':values['orders']/values['visitors'] if values['visitors'] else None,
                   'basket':values['revenue']/values['orders'] if values['orders'] else None}
            metric_samples.append(values['revenue'])
        else:
            day = {key:values[key] for key in samples}
            metric_samples.append(profit(values))
        for key, value in day.items():
            if value is not None:
                samples[key].append(value)

    def describe(key, label, values):
        n = len(values)
        mean = sum(values, Decimal(0))/n if n else None
        standard_deviation = (sum(((value-mean)**2 for value in values), Decimal(0))/(n-1)).sqrt() if n >= 2 else None
        relative = standard_deviation/abs(mean)*100 if standard_deviation is not None and mean else None
        return {'key':key, 'label':label, 'n':n, 'missing_days':len(daily)-n,
                'mean':str(mean) if mean is not None else None,
                'stddev':str(standard_deviation) if standard_deviation is not None else None,
                'relative_percent':str(relative) if relative is not None else None}

    factors = [describe(key, SCENARIOS[scenario]['labels'][key], values) for key,values in samples.items()]
    return {'window':scope['baseline'], 'filters':scope['filters'], 'days':len(daily),
            'missing_dates':expected_days-len(daily),
            'metric':describe('metric', SCENARIOS[scenario]['metric'], metric_samples), 'factors':factors,
            'notice':'基期每日数据的样本标准差（n-1）；相对波动为标准差除以均值绝对值。它描述历史样本，不是预测区间、因果效应或执行收益。每日数据可能存在周期性与相关性。'}
