import copy
import re
from datetime import date, timedelta
from decimal import Decimal as D
from .datasets import DIMENSIONS, MEASURES
from .attribution import multiplicative, additive, shapley, ratio_slices, number
from .scenarios import SCENARIOS


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


def totals(rows):
    return {k: sum((D(r[k]) for r in rows), D(0)) for k in MEASURES}


def factor_values(scenario, values):
    if scenario == 'ecommerce':
        if not values['visitors'] or not values['orders']:
            raise ValueError('访问或订单为零，当前乘法口径无法定义客单价；请查看原始总量')
        return dict(visitors=values['visitors'], conversion=values['orders']/values['visitors'], basket=values['revenue']/values['orders'])
    return {k: values[k] for k in SCENARIOS['consumer']['current']}


def profit(values):
    return values['revenue']-sum(values[k] for k in ('material','logistics','commission','other','tax'))


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
    else:
        breakdown = additive(factors['baseline'], factors['current'], {k:1 if k == 'revenue' else -1 for k in factors['baseline']}, labels)
    dimension = scope['group_by']
    cells = []
    ratio_pairs = {p:{} for p in selected}
    for value in sorted({r[dimension] for r in (*selected['baseline'],*selected['current'])}):
        values = {p: totals([r for r in group if r[dimension] == value]) for p,group in selected.items()}
        b,c = (v['revenue'] if scenario == 'ecommerce' else profit(v) for v in values.values())
        cells.append(dict(dimension=dimension, value=value, baseline=str(b), current=str(c), delta=str(c-b), contribution_rate=str((c-b)/breakdown.delta) if breakdown.delta else None))
        for p,v in values.items(): ratio_pairs[p][value] = (profit(v),v['revenue'])
    trends = []
    for p,group in selected.items():
        for day in sorted({r['date'] for r in group}):
            v = totals([r for r in group if r['date'] == day])
            trends.append(dict(date=day, period=p, value=str(v['revenue'] if scenario == 'ecommerce' else profit(v)), spend=str(v['spend']), visits=str(v['visitors'])))
    result = dict(scenario_id=scenario,title=SCENARIOS[scenario]['name'],metric=SCENARIOS[scenario]['metric'],
                  dataset_version=version,algorithm_version='decimal-v2',data_kind='版本化日聚合数据',
                  breakdown=breakdown.as_dict(), scope=scope, drilldown=cells, trends=trends,
                  parameters={k:str(v) for k,v in factors['current'].items()},
                  evidence_status='数学分解已完成，统计验证待执行',limitations=['访问次数可加总，不代表跨日期去重访客。','归因贡献解释数学变化，不直接证明因果。'])
    if scenario == 'consumer':
        result['margin_breakdown'] = shapley(factors['baseline'],factors['current'],lambda v:100*profit(v)/v['revenue'],labels,'百分点').as_dict()
        result['dimension_margin'] = ratio_slices(ratio_pairs['baseline'],ratio_pairs['current'],{}).as_dict()
        result['gross_margin'] = {p:str(100*(v['revenue']-v['material'])/v['revenue']) for p,v in summed.items()}
    return result


def simulate_snapshot(snapshot: dict, changes: dict) -> dict:
    scenario = snapshot['scenario_id']
    base = snapshot.get('parameters', SCENARIOS[scenario]['current'])
    if not changes or set(changes)-set(base):
        raise ValueError('模拟因子无效')
    values = {k:number(v) for k,v in base.items()}
    for k,v in changes.items():
        value = number(v)
        if value < 0 or value > D('1e12'):
            raise ValueError('模拟值超出范围')
        if k == 'conversion' and value > 1:
            raise ValueError('当前样例订单转化因子上限为 1')
        values[k] = value
    prediction = values['visitors']*values['conversion']*values['basket'] if scenario == 'ecommerce' else profit(values)
    if scenario == 'consumer' and not values['revenue']:
        raise ValueError('营收必须大于零')
    return dict(prediction=str(prediction), improvement=str(prediction-D(snapshot['breakdown']['current'])),
                parameters={k:str(v) for k,v in values.items()},kind='条件性点估计',interval=None,
                assumptions='基于本会话数据快照；其他因子不变，不含执行成本。')
