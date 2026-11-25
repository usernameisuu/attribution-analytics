"""Scoped descriptive comparisons for candidate questions, not statistical tests."""
from decimal import Decimal


_RULES = {
    'visitors': ('channel', '访问次数', '次', 'visitors', None, 1),
    'conversion': ('channel', '订单数 / 访问次数', '订单/次', 'orders', 'visitors', 1),
    'basket': ('category', '营收 / 订单数', '元/单', 'revenue', 'orders', 1),
    'revenue': ('channel', '营收', '元', 'revenue', None, 1),
    'material': ('category', '原材料成本 / 营收', '%', 'material', 'revenue', 100),
    'logistics': ('region', '物流成本 / 订单数', '元/单', 'logistics', 'orders', 1),
    'commission': ('channel', '佣金 / 营收', '%', 'commission', 'revenue', 100),
}


def observations(items, selected, limit=20):
    """Populate descriptive observations using only already scoped daily rows.

    Comparisons use ratios of totals, not averages of row-level ratios.  Results
    are sorted by absolute change, and do not adjudicate the hypotheses.
    """
    for item in items:
        dimension, metric, unit, numerator, denominator, scale = _RULES[item['factor_key']]
        groups = {}
        for period in ('baseline', 'current'):
            for row in selected[period]:
                values = groups.setdefault(row[dimension], {
                    'baseline': [Decimal(0), Decimal(0), False],
                    'current': [Decimal(0), Decimal(0), False]})
                values[period][0] += Decimal(row[numerator])
                values[period][2] = True
                if denominator:
                    values[period][1] += Decimal(row[denominator])
        compared = []
        for name, values in groups.items():
            def measure(period):
                num, den, present = values[period]
                if not present:
                    return None
                if denominator:
                    return num / den * scale if den else None
                return num
            baseline, current = measure('baseline'), measure('current')
            delta = current-baseline if baseline is not None and current is not None else None
            compared.append((name, baseline, current, delta))
        compared.sort(key=lambda row: (row[3] is None, -abs(row[3]) if row[3] is not None else Decimal(0), row[0]))
        item['evidence'] = [{
            'kind': 'descriptive_comparison', 'dimension': dimension, 'metric': metric,
            'unit': unit, 'delta_unit': '百分点' if unit == '%' else unit,
            'groups': [{'value': name, 'baseline': str(base) if base is not None else None,
                        'current': str(current) if current is not None else None,
                        'delta': str(delta) if delta is not None else None}
                       for name, base, current, delta in compared[:limit]],
            'total_groups': len(compared), 'truncated': len(compared) > limit,
            'note': '比率按各期总量计算；分组当期没有记录或分母为零时不计算。排序只表示数值差异，不代表贡献或统计显著性。',
        }]
        item['limitations'].append('此处是描述性比较，未执行统计检验，不能确认或排除此问题。')
    return items
