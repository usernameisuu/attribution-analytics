"""Render candidate questions and their saved descriptive observations."""
from html import escape


def _cell(value):
    if value is None:
        return '不适用'
    # User-supplied dimension names must not alter Markdown structure or inject HTML.
    value = escape(str(value), quote=False).replace('\\', '\\\\')
    for char in ('|', '[', ']', '(', ')', '*', '_', '`', '#'):
        value = value.replace(char, '\\' + char)
    if value.startswith(('- ', '+ ')):
        value = '\\' + value
    return value.replace('\r', ' ').replace('\n', ' ')


def hypothesis_sections(items, checks=()):
    if not items:
        return []
    rows = ['\n## 待验证问题\n', '以下为规则候选问题，尚未执行统计验证。\n']
    labels = {'channel': '渠道', 'region': '区域', 'category': '品类', 'segment': '客群'}
    for candidate in items:
        rows.append(f"### {_cell(candidate['question'])}\n")
        rows.append(f"状态：{_cell(candidate['status_label'])}；对应因子：{_cell(candidate['factor_label'])}。\n")
        for evidence in candidate.get('evidence', []):
            if evidence.get('kind') != 'descriptive_comparison':
                continue
            dim = labels.get(evidence['dimension'], evidence['dimension'])
            rows.append(f"按{_cell(dim)}的描述性比较：{_cell(evidence['metric'])}（{_cell(evidence['unit'])}）。\n")
            rows += [f"| 分组 | 基期 | 现期 | 变化（{_cell(evidence['delta_unit'])}） |", '| --- | ---: | ---: | ---: |']
            for group in evidence['groups']:
                rows.append('| ' + ' | '.join(_cell(group[key]) for key in ('value', 'baseline', 'current', 'delta')) + ' |')
            if evidence.get('truncated'):
                rows.append(f"\n仅展示 {len(evidence['groups'])} / {evidence['total_groups']} 个分组。")
            rows.append(f"\n{_cell(evidence['note'])}\n")
        factor = candidate.get('factor_key')
        linked = [check for check in checks if factor and check.get('factor_key') == factor]
        if linked:
            rows.append('\n相关逐日检验（按因子关联，不直接验证此问题；完整数值及限制见检验章节）：\n')
            for check in linked:
                status = '已计算' if check.get('status') == 'computed' else f"无法计算：{check.get('reason') or '原因未记录'}"
                rows.append(f"- {_cell(check.get('metric', '旧检验未记录指标'))}：{_cell(status)}")
        rows.append('此问题尚未完成统计验证，以上数值不能确认因果。\n')
    return rows


def simulation_section(items, factors, metric='指标', include_margin=False):
    if not items:
        return []
    labels = {factor['key']: factor['label'] for factor in factors}
    rows = ['\n## What-If 情景对比\n', '条件性点估计；收益区间暂无依据。\n',
            f'| 情景 | 调整因子及模拟值 | 模拟{_cell(metric)}（元） | {_cell(metric)}相对现期变化（元） |',
            '| --- | --- | ---: | ---: |']
    for item in items:
        changes = '；'.join(f"{labels.get(key, key)} = {value}" for key,value in item['changes'].items())
        rows.append('| ' + ' | '.join(_cell(value) for value in
                    (item['name'], changes, item['prediction'], item['improvement'])) + ' |')
    if include_margin:
        rows += ['\n模拟净利润率及其相对现期的变化：\n',
                 '| 情景 | 模拟净利润率（%） | 相对现期变化（百分点） | 说明 |',
                 '| --- | ---: | ---: | --- |']
        for item in items:
            margin = item.get('margin') or {}
            rows.append('| ' + ' | '.join(_cell(value) for value in
                        (item['name'], margin.get('prediction'), margin.get('improvement'),
                         margin.get('reason') or ('旧情景未记录，请重新计算' if not margin else '按模拟净利润除以模拟营收'))) + ' |')
    rows.append('\n模型假设：其他因子保持现期值，不含执行成本或因子联动。\n')
    return rows


def drilldown_section(items, metric, limit=200):
    if not items:
        return []
    labels = {'channel':'渠道', 'region':'区域', 'category':'品类', 'segment':'客群'}
    entries = []
    for parent in items:
        entries.append((labels.get(parent['dimension'], parent['dimension']), parent['value'], '', '',
                        parent['baseline'], parent['current'], parent['delta']))
        for child in parent.get('children', []):
            entries.append((labels.get(parent['dimension'], parent['dimension']), parent['value'],
                            labels.get(child['dimension'], child['dimension']), child['value'],
                            child['baseline'], child['current'], child['delta']))
    rows = ['\n## 维度下钻\n',
            f"指标：{_cell(metric)}（元）。二级分组属于对应一级分组，两层数值不能重复相加。\n",
            '| 一级维度 | 一级值 | 二级维度 | 二级值 | 基期 | 现期 | 变化（元） |',
            '| --- | --- | --- | --- | ---: | ---: | ---: |']
    rows.extend('| ' + ' | '.join(_cell(value) for value in entry) + ' |' for entry in entries[:limit])
    if len(entries) > limit:
        rows.append(f'\n为控制报告长度，仅展示 {limit} / {len(entries)} 行；完整下钻数据见 Excel 草稿。')
    return rows


def trend_section(points, metric, limit=120):
    if not points:
        return []
    ordered = sorted(points, key=lambda point:(point['date'], point['period']))
    rows = ['\n## 每日趋势\n', f"当前分析范围的每日{_cell(metric)}（元）；基期与现期按实际日期展示。\n",
            '| 日期 | 比较期 | 指标值（元） |', '| --- | --- | ---: |']
    for point in ordered[:limit]:
        period = {'baseline':'基期', 'current':'现期'}.get(point['period'], point['period'])
        rows.append('| ' + ' | '.join(_cell(value) for value in (point['date'], period, point['value'])) + ' |')
    if len(ordered) > limit:
        rows.append(f'\n为控制报告长度，仅展示 {limit} / {len(ordered)} 行；完整每日数据见 Excel 草稿。')
    return rows


def sensitivity_section(data):
    if not data:
        return []
    rows = ['\n## 当前公式局部敏感性\n', f"{_cell(data['notice'])}\n"]
    if data['status'] != 'available':
        return rows
    rows += ['因子增加一个原始单位时的理论指标变化；订单转化因子的一个单位为 100 个百分点。\n',
             '| 因子 | 当前因子值 | 每单位指标变化（元） | 公式相对弹性 | 不适用原因 |',
             '| --- | ---: | ---: | ---: | --- |']
    for item in data['rows']:
        rows.append('| ' + ' | '.join(_cell(value) for value in
                    (item['label'], item['current'], item['per_unit'], item['elasticity'], item.get('reason') or '—')) + ' |')
    return rows


def variability_section(data):
    if not data:
        return []
    rows = ['\n## 基期每日波动参考\n', f"{_cell(data['notice'])}\n"]
    if data['status'] != 'available':
        return rows
    rows += [f"基期：{_cell(' 至 '.join(data['window']))}；筛选：{_cell(data['filters'])}；观察 {_cell(data['days'])} 天，缺少 {_cell(data['missing_dates'])} 天；数据版本：{_cell(data['dataset_version'])}；摘要：{_cell(data['data_digest'])}。\n",
             '样本少于 2 天时标准差不适用；均值为零时相对波动不适用。\n',
             '| 指标或因子 | 有效天数 | 缺失天数 | 日均值 | 样本标准差 | 相对波动（%） |',
             '| --- | ---: | ---: | ---: | ---: | ---: |']
    for item in [data['metric'], *data['factors']]:
        rows.append('| ' + ' | '.join(_cell(item[key]) for key in
                    ('label', 'n', 'missing_days', 'mean', 'stddev', 'relative_percent')) + ' |')
    return rows


def action_section(items):
    if not items:
        return []
    rows = ['\n## 行动清单草稿\n', '由分析师填写，尚不代表已批准或实际收益。\n',
            '| 动作 | 关联因子（数学贡献） | 责任岗位 | 预计周期 | 预计收益与依据 |',
            '| --- | --- | --- | --- | --- |']
    for item in items:
        factor = f"{item['factor_label']}（{item['factor_contribution']} 元）"
        duration = f"{item['estimated_days']} 天" if item.get('estimated_days') is not None else '待补充'
        benefit = (f"{item['estimated_benefit']} 元；{item['benefit_basis']}（分析师估计）"
                   if item.get('estimated_benefit') is not None else
                   (f"暂无金额；{item['benefit_basis']}" if item.get('benefit_basis') else '暂无依据'))
        rows.append('| ' + ' | '.join(_cell(value) for value in
                    (item['action'], factor, item.get('owner_role') or '待补充', duration, benefit)) + ' |')
    return rows


def event_section(result):
    if not result:
        return []
    mode = '归档时匹配，后续事件变更不影响此快照。' if result.get('mode') == 'archived' else '每次导出重新匹配当前授权事件。'
    rows = ['\n## 业务事件关联线索\n',
            f"匹配时间（UTC）：{_cell(result['checked_at'])}；{mode}\n",
            f"{_cell(result['notice'])}\n"]
    if result['status'] != 'available':
        return rows
    rows.append(f"现期窗口：{_cell(' 至 '.join(result['current_window']))}；筛选：{_cell(result['filters'])}。\n")
    if not result['events']:
        rows.append('当前检查范围内没有匹配事件。\n')
        return rows
    rows += ['| 事件 | 开始 | 结束 | 适用范围 | 来源 | 匹配依据 | 证据状态 |', '| --- | --- | --- | --- | --- | --- | --- |']
    for item in result['events']:
        rows.append('| ' + ' | '.join(_cell(item.get(key, '旧归档未记录匹配依据')) for key in
                    ('title', 'start', 'end', 'scope', 'source', 'match_basis', 'evidence_status')) + ' |')
    return rows


def statistical_section(items):
    if not items:
        return []
    rows=['\n## 每日均值检验（内置）\n']
    for item in items:
        rows.append(f"指标：{_cell(item['metric'])}；单位：{_cell(item['unit'])}；样本：{_cell(item['sample_unit'])}。\n")
        factor = (item['factor_key'] or '整体指标') if 'factor_key' in item else '旧记录未保存'
        if item.get('group_value') is not None:
            rows.append(f"分组对比：{_cell(item.get('group_dimension'))} = {_cell(item['group_value'])}，与同范围内其他分组比较。\n")
        rows.append(f"检验记录：候选因子 {_cell(factor)}；时间（UTC）{_cell(item.get('calculated_at', '旧记录未保存'))}；方法版本 {_cell(item.get('method_version', '旧记录未保存'))}；SciPy {_cell(item.get('scipy_version', '旧记录未保存'))}。\n")
        rows.append(f"检验数据版本：{_cell(item.get('dataset_version', '旧记录未保存'))}；摘要：{_cell(item.get('data_digest', '旧记录未保存'))}；范围：{_cell(item.get('scope', '旧记录未保存'))}。\n")
        base = item.get('baseline_mean_decimal') or item.get('baseline_mean')
        current = item.get('current_mean_decimal') or item.get('current_mean')
        difference = item.get('mean_difference_decimal') or item.get('mean_difference')
        rows.append(f"基期 n={item['baseline_n']}、均值={_cell(base)}；现期 n={item['current_n']}、均值={_cell(current)}；差值={_cell(difference)} {_cell(item.get('delta_unit', item['unit']))}。\n")
        if item.get('method_version') == 'daily-welch-v5':
            rows.append('均值按 Decimal 80 位精度计算（除法可能舍入）；检验对日值减去共同基准后使用浮点计算。\n')
        if item['status']=='computed':
            p_text='小于浮点可表示范围' if item.get('p_value_underflow') else _cell(item['p_value'])
            rows.append(f"Welch 双侧检验：t={_cell(item['statistic'])}，df={_cell(item['degrees_of_freedom'])}，p={p_text}；{item['confidence_level']*100:g}% 置信区间 [{_cell(item['interval']['low'])}, {_cell(item['interval']['high'])}] {_cell(item.get('delta_unit', item['unit']))}。\n")
        else:
            rows.append(f"无法计算：{_cell(item['reason'])}\n")
        rows.extend(f"- {_cell(limit)}" for limit in item['limitations'])
    return rows


def markdown_report_text(snapshot):
    s, b = snapshot, snapshot['breakdown']
    rows = [f"# {_cell(s['title'])}\n", '状态：数学分解草稿，未完成统计归因验证。\n',
            f"数据：{_cell(s['dataset_version'])}；算法：{_cell(s['algorithm_version'])}\n",
            f"基期：{_cell(b['baseline'])}；现期：{_cell(b['current'])}；差额：{_cell(b['delta'])} {_cell(b['unit'])}\n",
            '| 因子 | 贡献量 |\n| --- | ---: |']
    if s.get('metric_definition_version'):
        rows.insert(3, f"指标口径版本：{_cell(s['metric_definition_version'])}\n")
    if s.get('archive_context'):
        archive = s['archive_context']
        rows.insert(1, f"归档草稿：{_cell(archive['id'])}；时间（UTC）：{_cell(archive['created_at'])}；内容摘要：{_cell(archive['digest'])}。\n")
    rows.extend(f"| {_cell(factor['label'])} | {_cell(factor['contribution'])} |" for factor in b['factors'])
    margin = s.get('margin_breakdown')
    if margin:
        rows += ['\n## 样例净利润率分解\n',
                 f"基期：{_cell(margin['baseline'])}%；现期：{_cell(margin['current'])}%；变化：{_cell(margin['delta'])} 百分点。",
                 f"方法：{_cell(margin['method'])}；贡献残差：{_cell(margin['residual'])} 百分点。数学分解不证明因果。\n",
                 '| 因子 | 贡献（百分点） |', '| --- | ---: |']
        rows.extend(f"| {_cell(factor['label'])} | {_cell(factor['contribution'])} |" for factor in margin['factors'])
    elif s.get('margin_status', {}).get('status') == 'not_applicable':
        rows += ['\n## 样例净利润率分解\n', f"不适用：{_cell(s['margin_status'].get('reason'))}\n"]
    if 'scope' in s:
        scope = s['scope']
        rows += ['\n## 数据范围\n', f"类型：{_cell(s['data_kind'])}；SHA-256：{_cell(s.get('data_digest', ''))}\n",
                 f"基期：{_cell(' 至 '.join(scope['baseline']))}；现期：{_cell(' 至 '.join(scope['current']))}\n",
                 f"筛选：{_cell(scope['filters'])}；分组：{_cell(scope['group_by'])}\n"]
    rows.extend(drilldown_section(s.get('drilldown', []), s.get('metric', '指标')))
    rows.extend(trend_section(s.get('trends', []), s.get('metric', '指标')))
    rows.extend(hypothesis_sections(s.get('hypotheses', []), s.get('statistical_checks', [])))
    rows.extend(statistical_section(s.get('statistical_checks', [])))
    rows.extend(event_section(s.get('report_events')))
    rows.extend(sensitivity_section(s.get('report_sensitivity')))
    rows.extend(variability_section(s.get('report_variability')))
    rows.extend(simulation_section(s.get('simulation_scenarios', []), b['factors'], s.get('metric', '指标'), s.get('scenario_id') == 'consumer'))
    rows.extend(action_section(s.get('action_items', [])))
    if s.get('report_note'):
        note = s['report_note']
        rows += ['\n## 分析师说明\n', f"作者：{_cell(note['author'])}；更新时间：{_cell(note['updated_at'])}。\n",
                 _cell(note['text']), '\n此说明由分析师填写，不代表已发布或验证。']
    rows += ['\n## 分析边界\n', *[_cell(value) for value in s['limitations']],
             '\n本草稿不包含尚未执行的检验、事件因果证明或收益区间。']
    return '\n'.join(rows)
