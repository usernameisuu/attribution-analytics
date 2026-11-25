import copy
import re
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal as D
from .datasets import DIMENSIONS, MEASURES
from .attribution import multiplicative, additive, shapley, ratio_slices, number, calculation_precision, validate_input_precision
from .scenarios import SCENARIOS
from .metric_catalog import VERSION as METRIC_DEFINITION_VERSION
from .hypotheses import candidates
from .descriptive import observations


def default_scope(rows: list[dict]) -> dict:
    last = max(date.fromisoformat(r['date']) for r in rows)
    return dict(baseline=[(last-timedelta(days=59)).isoformat(), (last-timedelta(days=30)).isoformat()],
                current=[(last-timedelta(days=29)).isoformat(),last.isoformat()], filters={}, group_by='channel')


def validate_scope(scope: dict, rows: list[dict]) -> dict:
    if not isinstance(scope,dict) or set(scope) != {'baseline','current','filters','group_by'}:
        raise ValueError("分析范围字段无效")
    if not isinstance(scope['group_by'],str) or scope['group_by'] not in DIMENSIONS or not isinstance(scope['filters'], dict):
        raise ValueError("不支持的下钻维度")
    if set(scope['filters']) - set(DIMENSIONS):
        raise ValueError("筛选字段未授权")
    for key, value in scope['filters'].items():
        if not isinstance(value, str) or value not in {r[key] for r in rows}:
            raise ValueError(f"未知的 {key} 筛选值")
    for period in ('baseline','current'):
        bounds = scope[period]
        if not isinstance(bounds, list) or len(bounds) != 2 or any(not isinstance(v,str) for v in bounds):
            raise ValueError("比较期需要起止日期")
        start, end = [date.fromisoformat(v) for v in bounds]
        if bounds != [start.isoformat(),end.isoformat()]:
            raise ValueError('日期必须使用 YYYY-MM-DD 格式')
        if start > end or (end-start).days > 366:
            raise ValueError("日期区间无效")
        available = {r['date'] for r in rows}
        if any((start+timedelta(days=i)).isoformat() not in available for i in range((end-start).days+1)):
            raise ValueError("所选比较期的数据不完整")
    if not (scope['baseline'][1] < scope['current'][0] or scope['current'][1] < scope['baseline'][0]):
        raise ValueError("当前检验不接受重叠比较期")
    if (date.fromisoformat(scope['baseline'][1])-date.fromisoformat(scope['baseline'][0])).days != (date.fromisoformat(scope['current'][1])-date.fromisoformat(scope['current'][0])).days:
        raise ValueError("当前总量比较需要等长周期")
    return copy.deepcopy(scope)


def rule_plan(question: str, previous: dict, rows: list[dict], parents: list[dict]) -> dict:
    scope = copy.deepcopy(previous)
    remainder = question.strip()
    if question.strip() == '返回上一级':
        if not parents:
            raise ValueError('已经是最上级范围')
        return validate_scope(parents[-1], rows)
    recognized = False
    if '返回全国' in question:
        scope['filters'].pop('region', None)
        recognized = True
        remainder = remainder.replace('返回全国','')
    if '清除筛选' in question or '整体' in question:
        scope['filters'] = {}
        recognized = True
        remainder = remainder.replace('清除筛选','').replace('整体','')
    names = dict(channel='渠道',region='区域',category='品类',segment='客群')
    for key in DIMENSIONS:
        matches = [v for v in sorted({r[key] for r in rows}) if v in question]
        if len(matches) > 1:
            raise ValueError(f'请明确一个{names[key]}筛选值，或选择按{names[key]}分组')
        if matches:
            scope['filters'][key] = matches[0]
            recognized = True
            remainder = remainder.replace(matches[0],'')
        if f'按{names[key]}' in question or f'看{names[key]}' in question:
            scope['group_by'] = key
            recognized = True
            remainder = remainder.replace(f'按{names[key]}','').replace(f'看{names[key]}','')
    if not recognized and question.strip() not in ('分析','开始分析','重新分析'):
        raise ValueError('规则模式无法明确理解问题，请使用维度筛选，或启用已配置的 DeepSeek')
    for word in ('重新分析','开始分析','分析','只看','查看','看'):
        remainder = remainder.replace(word,'')
    if re.sub(r'[\s，,；;。！!、]+','',remainder):
        raise ValueError('规则模式存在无法解析的条件，请拆成明确的维度筛选或使用 DeepSeek')
    return validate_scope(scope, rows)


def select_rows(rows, scope, period):
    start, end = scope[period]
    return [r for r in rows if start <= r['date'] <= end and all(r[k] == v for k,v in scope['filters'].items())]


@calculation_precision
def totals(rows):
    values = {k:D(0) for k in MEASURES}
    for row in rows:
        for key in MEASURES:
            value = D(row[key])
            validate_input_precision(value)
            values[key] += value
    return values


@calculation_precision
def group_totals(rows, dimension):
    """Aggregate once per row, rather than rescanning for every group."""
    grouped = {}
    for row in rows:
        group = row[dimension]
        if group not in grouped:
            grouped[group] = {key: D(0) for key in MEASURES}
        values = grouped[group]
        for key in MEASURES:
            value = D(row[key])
            validate_input_precision(value)
            values[key] += value
    return grouped


def factor_values(scenario, values):
    if scenario == 'ecommerce':
        if not values['visitors'] or not values['orders']:
            raise ValueError('访问或订单为零，当前乘法口径无法定义客单价；请查看原始总量')
        return dict(visitors=values['visitors'], conversion=values['orders']/values['visitors'], basket=values['revenue']/values['orders'])
    return {k: values[k] for k in SCENARIOS['consumer']['current']}


def profit(values):
    return values['revenue']-sum(values[k] for k in ('material','logistics','commission','other','tax'))


@calculation_precision
def analyze(scenario: str, rows: list[dict], scope: dict, version: str) -> dict:
    scope = validate_scope(scope, rows)
    selected = {p: select_rows(rows, scope, p) for p in ('baseline','current')}
    if any(not r for r in selected.values()):
        raise ValueError('筛选后没有可比较数据')
    summed = {p: totals(r) for p,r in selected.items()}
    factors = {p: factor_values(scenario, v) for p,v in summed.items()}
    labels = {**SCENARIOS[scenario]['labels'], 'visitors':'访问次数'}
    if scenario == 'ecommerce':
        breakdown = multiplicative(factors['baseline'], factors['current'], labels)
        # The original totals are authoritative; ratios can have repeating decimals.
        breakdown = replace(breakdown, baseline=summed['baseline']['revenue'], current=summed['current']['revenue'])
    else:
        breakdown = additive(factors['baseline'], factors['current'], {k:1 if k == 'revenue' else -1 for k in factors['baseline']}, labels)
    dimension = scope['group_by']
    secondary_dimension = 'region' if dimension != 'region' else 'channel'
    grouped = {}
    for period, rows_in_period in selected.items():
        for row in rows_in_period:
            key = (row[dimension], row[secondary_dimension])
            values = grouped.setdefault(key, {'baseline': D(0), 'current': D(0)})
            amount = D(row['revenue']) if scenario == 'ecommerce' else (
                D(row['revenue']) - sum((D(row[field]) for field in ('material','logistics','commission','other','tax')), D(0))
            )
            values[period] += amount
    children_by_parent = {}
    for (parent, child), amounts in sorted(grouped.items()):
        child_delta = amounts['current'] - amounts['baseline']
        children_by_parent.setdefault(parent, []).append(dict(
            dimension=secondary_dimension, value=child,
            baseline=str(amounts['baseline']), current=str(amounts['current']), delta=str(child_delta),
            contribution_rate=str(child_delta/breakdown.delta) if breakdown.delta else None,
        ))
    cells = []
    ratio_pairs = {p:{} for p in selected}
    grouped_totals = {p: group_totals(group, dimension) for p,group in selected.items()}
    empty_totals = {key: D(0) for key in MEASURES}
    for value in sorted(set(grouped_totals['baseline']) | set(grouped_totals['current'])):
        values = {p: grouped_totals[p].get(value, empty_totals) for p in selected}
        b,c = (v['revenue'] if scenario == 'ecommerce' else profit(v) for v in values.values())
        cells.append(dict(dimension=dimension, value=value, baseline=str(b), current=str(c), delta=str(c-b), contribution_rate=str((c-b)/breakdown.delta) if breakdown.delta else None, children=children_by_parent[value]))
        for p,v in values.items(): ratio_pairs[p][value] = (profit(v),v['revenue'])
    trends = []
    for p,group in selected.items():
        daily = group_totals(group, 'date')
        for day, v in sorted(daily.items()):
            trends.append(dict(date=day, period=p, value=str(v['revenue'] if scenario == 'ecommerce' else profit(v)), spend=str(v['spend']), visits=str(v['visitors'])))
    result = dict(scenario_id=scenario,title=SCENARIOS[scenario]['name'],metric=SCENARIOS[scenario]['metric'],
                  dataset_version=version,algorithm_version='decimal-v4',metric_definition_version=METRIC_DEFINITION_VERSION,data_kind='版本化日聚合数据',
                  breakdown=breakdown.as_dict(), scope=scope, drilldown=cells, trends=trends,
                  hypotheses=observations(candidates(scenario, breakdown), selected),
                  parameters={k:str(v) for k,v in factors['current'].items()},
                  evidence_status='数学分解已完成，统计验证待执行',limitations=['访问次数可加总，不代表跨日期去重访客。','归因贡献解释数学变化，不直接证明因果。'])
    if scenario == 'consumer':
        # Profit can be compared even when a period's revenue is zero. A margin
        # is undefined in that case, so never replace it with 0 or infinity.
        zero_revenue_periods = [p for p, values in summed.items() if values['revenue'] == 0]
        result['gross_margin'] = {
            p: str(100 * (values['revenue'] - values['material']) / values['revenue'])
            if values['revenue'] else None
            for p, values in summed.items()
        }
        result['gross_margin_definition'] = '样例口径：仅扣除原材料成本；不代表已确认的财务毛利率'
        result['limitations'].append(result['gross_margin_definition'])
        if zero_revenue_periods:
            names = {'baseline': '基期', 'current': '现期'}
            reason = f"{'、'.join(names[p] for p in zero_revenue_periods)}营收为零，利润率及其贡献无法计算。"
            result['margin_status'] = {'status': 'not_applicable', 'reason': reason}
            result['limitations'].append(reason)
        else:
            result['margin_breakdown'] = shapley(factors['baseline'],factors['current'],lambda v:100*profit(v)/v['revenue'],labels,'百分点').as_dict()
            result['dimension_margin'] = ratio_slices(ratio_pairs['baseline'],ratio_pairs['current'],{}).as_dict()
            result['margin_status'] = {'status': 'available', 'reason': None}
    return result


@calculation_precision
def simulate_snapshot(snapshot: dict, changes: dict) -> dict:
    scenario = snapshot['scenario_id']
    base = snapshot.get('parameters')
    if base is None:
        if snapshot.get('dataset_version') != 'prd-fixture-v1':
            raise ValueError('该快照未记录模拟参数，请重新创建分析')
        base = SCENARIOS[scenario]['current']
    if not changes or set(changes)-set(base):
        raise ValueError('模拟因子无效')
    values = {k:number(v) for k,v in base.items()}
    for k,v in changes.items():
        value = number(v)
        # Calculated current factors may exceed user input precision/range.
        # Keeping an existing value is not a new hypothetical input.
        if value != values[k]:
            validate_input_precision(value)
            if value < 0 or value > D('1e12'):
                raise ValueError('模拟值超出范围')
            if k == 'conversion' and value > 1:
                raise ValueError('当前样例订单转化因子上限为 1')
        values[k] = value
    if all(values[key] == number(base[key]) for key in values):
        # Derived ratios can repeat; unchanged parameters must reproduce the observed total.
        prediction = D(snapshot['breakdown']['current'])
    else:
        prediction = values['visitors']*values['conversion']*values['basket'] if scenario == 'ecommerce' else profit(values)
    result = dict(prediction=str(prediction), improvement=str(prediction-D(snapshot['breakdown']['current'])),
                  parameters={k:str(v) for k,v in values.items()},kind='条件性点估计',interval=None,
                  assumptions='基于本会话数据快照；未调整的因子保持现期值，不含执行成本，也未估计因子联动。')
    if scenario == 'consumer':
        current_revenue = number(base['revenue'])
        simulated_margin = 100 * prediction / values['revenue'] if values['revenue'] else None
        current_margin = 100 * D(snapshot['breakdown']['current']) / current_revenue if current_revenue else None
        reason = ('模拟营收为零，无法计算模拟利润率。' if simulated_margin is None else
                  '现期营收为零，无法计算较现期的利润率变化。' if current_margin is None else None)
        result['margin'] = {'prediction':str(simulated_margin) if simulated_margin is not None else None,
                            'improvement':str(simulated_margin-current_margin) if simulated_margin is not None and current_margin is not None else None,
                            'reason':reason}
    return result
