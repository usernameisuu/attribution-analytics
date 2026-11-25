"""Rule-generated questions for follow-up; these are not validated findings."""

_TEMPLATES = {
    'ecommerce': (
        ('visitors', '不同渠道或客群的访问变化，是否与整体访问变化有关？',
         ['按日期、渠道和客群统计的访问次数', '营销投放及活动记录']),
        ('conversion', '订单数与访问次数的比值变化，是否集中在特定渠道或客群？',
         ['按日期和细分维度统计的访问次数与订单数', '漏斗定义及订单归属规则']),
        ('basket', '订单平均金额变化，是否与品类或促销结构变化同时出现？',
         ['按日期和品类统计的订单数及订单金额', '促销、退款和退货口径']),
    ),
    'consumer': (
        ('revenue', '营收变化是否集中在特定渠道或品类？',
         ['按日期、渠道和品类统计的营收', '销量、价格及退款口径']),
        ('material', '原材料成本变化是否伴随成本率或产品结构变化？',
         ['按日期和品类统计的营收、原材料成本', '采购价格与单位用量']),
        ('logistics', '物流履约成本变化是否集中在特定区域或渠道？',
         ['按日期、区域和渠道统计的物流成本与订单量', '履约单价及配送结构']),
        ('commission', '渠道佣金变化是否伴随渠道结构或佣金费率变化？',
         ['按日期和渠道统计的佣金及营收', '佣金费率与结算规则']),
    ),
}


def candidates(scenario, breakdown):
    if scenario not in _TEMPLATES:
        raise ValueError('未知业务线')
    factors = {factor.key: factor for factor in breakdown.factors}
    result = []
    for key, question, required in _TEMPLATES[scenario]:
        factor = factors.get(key)
        if factor is None:
            raise ValueError('缺少假设所需的拆解因子')
        result.append({
            'id': f'rule-{key}', 'question': question, 'required_data': list(required),
            'status': 'pending', 'status_label': '待验证', 'source': 'rule',
            'factor_key': key, 'factor_label': factor.label,
            'factor_contribution': str(factor.contribution), 'contribution_unit': breakdown.unit,
            'evidence': [], 'limitations': ['拆解贡献是数学结果，不验证此问题或证明因果关系。'],
        })
    return result
