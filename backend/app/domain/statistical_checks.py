"""Fixed daily-aggregate checks; does not execute user or model-generated code."""
from math import isfinite, ulp
from decimal import Decimal
from statistics import variance
from warnings import catch_warnings, simplefilter

from scipy.stats import ttest_ind

from .exploration import group_totals, profit, select_rows, validate_scope
from .attribution import calculation_precision
from .descriptive import _RULES


@calculation_precision
def daily_welch(scenario, rows, scope, confidence_level, factor_key=None, group_value=None):
    if scenario not in ('ecommerce', 'consumer'):
        raise ValueError('未知业务线')
    if not 0.8 <= confidence_level <= 0.99:
        raise ValueError('置信水平必须在 0.80 至 0.99 之间')
    allowed = {'ecommerce': {'visitors', 'conversion', 'basket'},
               'consumer': {'revenue', 'material', 'logistics', 'commission'}}
    if factor_key is not None and factor_key not in allowed[scenario]:
        raise ValueError('当前业务线不支持该候选指标')
    if group_value is not None and (not factor_key or not isinstance(group_value, str) or not group_value):
        raise ValueError('分组对比必须选择候选指标和分组')
    scope = validate_scope(scope, rows)
    samples = {}
    missing_denominator = missing_group = False
    if factor_key:
        dimension, label, unit, numerator, denominator, scale = _RULES[factor_key]
        metric = f'每日{label}'
        metric_unit = unit
    else:
        metric = '每日 GMV' if scenario == 'ecommerce' else '每日样例净利润'
        metric_unit = '元/日'
    if group_value is not None:
        matching = [r for period in ('baseline', 'current') for r in select_rows(rows, scope, period)]
        available = {r[dimension] for r in matching}
        if group_value not in available or len(available) < 2:
            raise ValueError('所选分组不存在或当前范围内没有其他分组')
        names = {'channel':'渠道', 'region':'区域', 'category':'品类', 'segment':'客群'}
        metric = f"{names[dimension]}「{group_value}」与其他{names[dimension]}的每日{label}差距"
        if unit == '%':
            metric_unit = '百分点'
    for period in ('baseline', 'current'):
        selected = select_rows(rows, scope, period)
        grouped = group_totals(selected, 'date')
        if not grouped:
            raise ValueError('筛选后没有可比较数据')
        if group_value is not None:
            group_days = group_totals((r for r in selected if r[dimension] == group_value), 'date')
            other_days = group_totals((r for r in selected if r[dimension] != group_value), 'date')
        raw = []
        for day, values in sorted(grouped.items()):
            if factor_key:
                group_values = [values] if group_value is None else [group_days.get(day), other_days.get(day)]
                if any(value is None for value in group_values):
                    missing_group = True
                    continue
                if denominator and any(not value[denominator] for value in group_values):
                    missing_denominator = True
                    continue
                measures = [value[numerator] / value[denominator] * scale if denominator else value[numerator]
                            for value in group_values]
                value = measures[0] - measures[1] if group_value is not None else measures[0]
            else:
                value = values['revenue'] if scenario == 'ecommerce' else profit(values)
            raw.append(value)
        samples[period] = raw
    first, second = samples['current'], samples['baseline']
    current_mean = sum(first, Decimal(0))/len(first) if first else None
    baseline_mean = sum(second, Decimal(0))/len(second) if second else None
    mean_difference = current_mean-baseline_mean if current_mean is not None and baseline_mean is not None else None
    result = {
        'method':'welch_two_sided_daily_mean', 'metric':metric, 'factor_key':factor_key,
        'group_dimension':dimension if group_value is not None else None, 'group_value':group_value,
        'unit':metric_unit, 'delta_unit':'百分点' if metric_unit == '%' else metric_unit,
        'scope':scope, 'confidence_level':confidence_level,
        'sample_unit':'每天所选分组减其余分组的指标差' if group_value is not None else '按当前筛选范围聚合的每日数值', 'current_n':len(first), 'baseline_n':len(second),
        'current_mean':None, 'baseline_mean':None, 'mean_difference':None,
        'current_mean_decimal':None, 'baseline_mean_decimal':None, 'mean_difference_decimal':None,
        'status':'not_applicable', 'reason':None,
        'statistic':None, 'degrees_of_freedom':None, 'p_value':None, 'p_value_underflow':False, 'interval':None,
        'limitations':[
            'Welch 双样本检验假定两组观察独立；每日经营数据可能存在自相关、周周期和共同冲击，独立性未经验证。',
            '检验针对每日均值差，不直接验证候选业务假设，也不证明因果关系。',
            '检验是在观察数据后选择的，结果可能受多重比较及选择偏差影响；未自动判定显著或排除假设。',
        ],
    }
    if factor_key:
        explanation = ('该检验比较两期每日分组差距的均值，分组与其余分组的每日指标先相减。'
                       if group_value is not None else '该检验比较所选范围内每日指标均值。')
        if denominator:
            explanation += '比率为逐日比率的简单均值，与两期总量之比不同。'
        if group_value is not None:
            explanation += '分组规模、结构及共同变化可能影响差距；未控制混杂，不能确认或排除候选问题。'
        else:
            explanation += '它不检验分组集中程度，不能确认或排除候选问题。'
        result['limitations'].append(explanation)
    if missing_group:
        result.update(reason='存在日期缺少所选分组或其他分组的记录，无法计算分组差距。',
                      current_mean=None, baseline_mean=None, mean_difference=None)
        return result
    if missing_denominator:
        result.update(reason='存在每日分母为零，未排除该日或计算检验。',
                      current_mean=None, baseline_mean=None, mean_difference=None)
        return result
    if min(len(first),len(second)) < 2:
        result['reason'] = '每个比较期至少需要两个每日观察值。'
        return result
    # Subtract a common exact Decimal anchor before conversion. Welch's
    # statistic and the difference of means are invariant to this translation.
    anchor = second[0]
    centered_current = [value-anchor for value in first]
    centered_baseline = [value-anchor for value in second]
    centered = centered_current + centered_baseline
    converted = [float(value) for value in centered]
    unique = sorted(set(centered))
    precision_loss = any(not isfinite(value) for value in converted) or len(set(converted)) < len(unique)
    if len(unique) > 1 and not precision_loss:
        smallest_gap = min(right-left for left,right in zip(unique,unique[1:]))
        max_ulp = max(Decimal.from_float(ulp(value)) for value in converted)
        error = max(abs(Decimal.from_float(value)-original) for value,original in zip(converted,centered))
        if max_ulp * 100 >= smallest_gap or error * 100 >= smallest_gap:
            precision_loss = True
    if precision_loss:
        result.update(reason='每日数值转换为浮点数会丢失精度，无法可靠执行检验。',
                      current_mean=None, baseline_mean=None, mean_difference=None)
        return result
    for key, exact in (('baseline_mean',baseline_mean),('current_mean',current_mean),('mean_difference',mean_difference)):
        result[f'{key}_decimal'] = str(exact)
        approximate = float(exact)
        # Do not expose a rounded absolute mean as though it were precise
        # enough to distinguish the daily data.
        if isfinite(approximate) and ((len(unique) == 1 and Decimal.from_float(approximate) == exact)
                                     or (len(unique) > 1 and abs(Decimal.from_float(approximate)-exact)*100 < smallest_gap)):
            result[key] = approximate
    first = converted[:len(first)]
    second = converted[len(first):]
    if variance(first) == 0 and variance(second) == 0:
        result['reason'] = '两期日数据均无波动，无法估计检验所需标准误。'
        return result
    with catch_warnings(record=True) as warnings:
        simplefilter('always', RuntimeWarning)
        test = ttest_ind(first, second, equal_var=False, alternative='two-sided')
        interval = test.confidence_interval(confidence_level=confidence_level)
    if any(issubclass(warning.category, RuntimeWarning) for warning in warnings):
        result['reason'] = '统计计算出现数值精度警告，无法可靠执行检验。'
        return result
    values = (test.statistic,test.df,test.pvalue,interval.low,interval.high)
    if not all(isfinite(float(value)) for value in values):
        result['reason'] = '检验结果不可计算，请检查样本波动与数据范围。'
        return result
    p_value=float(test.pvalue)
    result.update(status='computed',statistic=float(test.statistic),degrees_of_freedom=float(test.df),
                  p_value=p_value if p_value else None, p_value_underflow=p_value == 0,
                  interval={'low':float(interval.low),'high':float(interval.high)})
    return result
