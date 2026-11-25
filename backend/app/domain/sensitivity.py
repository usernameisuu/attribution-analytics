"""Local formula sensitivity, without estimating business or causal effects."""
from .attribution import calculation_precision, number
from .scenarios import SCENARIOS


@calculation_precision
def formula_sensitivity(snapshot):
    scenario = snapshot['scenario_id']
    source = snapshot.get('parameters')
    if source is None:
        if snapshot.get('dataset_version') != 'prd-fixture-v1':
            raise ValueError('该快照未记录计算敏感性所需的参数')
        source = SCENARIOS[scenario]['current']
    parameters = {key:number(value) for key,value in source.items()}
    metric = number(snapshot['breakdown']['current'])
    if scenario == 'ecommerce':
        derivatives = {'visitors':parameters['conversion']*parameters['basket'],
                       'conversion':parameters['visitors']*parameters['basket'],
                       'basket':parameters['visitors']*parameters['conversion']}
    elif scenario == 'consumer':
        derivatives = {key:number(1 if key == 'revenue' else -1) for key in parameters}
    else:
        raise ValueError('未知业务线')
    rows = []
    for factor in snapshot['breakdown']['factors']:
        key = factor['key']
        derivative = derivatives[key]
        elasticity = derivative * parameters[key] / metric if metric and parameters[key] else None
        rows.append({'key':key, 'label':factor['label'], 'current':str(parameters[key]),
                     'per_unit':str(derivative), 'elasticity':str(elasticity) if elasticity is not None else None,
                     'reason':('现期指标为零' if not metric else '现期因子为零' if not parameters[key] else None)})
    return {'metric':snapshot['metric'], 'rows':rows,
            'notice':'仅为当前公式的局部数学敏感性，假定其他因子不变；相对弹性使用带符号的现期指标，不是历史估计、因果效应、实际收益或收益区间。',
            'zero_metric_notice':'现期指标为零，相对弹性不适用。' if not metric else None}


def capture_formula_sensitivity(snapshot):
    """Capture at export time; old or incomplete snapshots remain explicitly unavailable."""
    try:
        return {'status':'available', **formula_sensitivity(snapshot)}
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return {'status':'unavailable', 'notice':'当前快照缺少计算所需口径或参数，无法生成公式敏感性。'}
