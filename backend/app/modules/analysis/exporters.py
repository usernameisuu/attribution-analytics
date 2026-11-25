"""Draft report exports from the saved analysis snapshot."""
from io import BytesIO
from html import escape, unescape
from functools import lru_cache
from copy import deepcopy
from decimal import Decimal, InvalidOperation, localcontext
import os
from pathlib import Path
import re
from datetime import date
from math import isfinite

from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.graphics.shapes import Circle, Drawing, Line, String
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFError, TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from .report import markdown_report_text

_XML_CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')


def spreadsheet(snapshot):
    """Keep all exported values as literal text to preserve decimals and prevent formulas."""
    workbook = Workbook()
    workbook.remove(workbook.active)

    def sheet(name, header, rows):
        page = workbook.create_sheet(name)
        page.append(header)
        for row in rows:
            page.append([_XML_CONTROL.sub('', str(value)) if value is not None else '不适用' for value in row])
        for cell in page[1]:
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = PatternFill('solid', fgColor='2B5362')
        for row in page.iter_rows(min_row=2):
            for cell in row:
                cell.data_type = 's'
                cell.alignment = Alignment(vertical='top', wrap_text=True)
        page.freeze_panes = 'A2'
        page.auto_filter.ref = page.dimensions
        for column in page.columns:
            page.column_dimensions[column[0].column_letter].width = 24
        return page

    b = snapshot['breakdown']
    scope = snapshot.get('scope', {})
    sheet('概要', ['项目', '值'], [
        ('状态', '数学分解草稿，未完成统计归因验证'), ('标题', snapshot['title']),
        ('归档信息', str(snapshot.get('archive_context', '未归档'))),
        ('数据版本', snapshot['dataset_version']), ('数据摘要', snapshot.get('data_digest', '无')),
        ('指标口径版本', snapshot.get('metric_definition_version', '未记录')), ('算法', snapshot['algorithm_version']),
        ('基期', b['baseline']), ('现期', b['current']), ('差额', b['delta']), ('单位', b['unit']),
        ('数字格式', '数值按原始精度作为文本保存，参与计算前需自行转换'),
        ('分析师说明', (snapshot.get('report_note') or {}).get('text', '未填写')),
        ('说明作者', (snapshot.get('report_note') or {}).get('author', '未填写')),
        ('说明更新时间', (snapshot.get('report_note') or {}).get('updated_at', '未填写')),
        ('分析范围', str(scope)), ('限制', '；'.join(snapshot.get('limitations', []))),
    ])
    sheet('因子贡献', ['因子', '基期', '现期', '贡献量', '贡献率'],
          [(f['label'], f['baseline'], f['current'], f['contribution'], f.get('contribution_rate')) for f in b['factors']])
    sensitivity = snapshot.get('report_sensitivity')
    if sensitivity:
        sensitivity_rows = [('说明', sensitivity['notice'], '', '', '')]
        sensitivity_rows.extend((item['label'], item['current'], item['per_unit'], item['elasticity'], item.get('reason') or '')
                                for item in sensitivity.get('rows', []))
        sheet('公式敏感性', ['因子','当前值或说明','每单位指标变化元','公式相对弹性','不适用原因'], sensitivity_rows)
    variability = snapshot.get('report_variability')
    if variability:
        variability_rows = [('说明', variability['notice'], '', '', '', '')]
        if variability['status'] == 'available':
            variability_rows.append(('范围', f"{variability['window'][0]} 至 {variability['window'][1]}；筛选 {variability['filters']}；缺少日期 {variability['missing_dates']} 天", '', '', '', ''))
            variability_rows.extend((item['label'], item['n'], item['missing_days'], item['mean'], item['stddev'], item['relative_percent'])
                                    for item in [variability['metric'], *variability['factors']])
        sheet('基期每日波动', ['指标或因子','有效天数或说明','缺失天数','日均值','样本标准差','相对波动百分比'], variability_rows)
    margin = snapshot.get('margin_breakdown')
    if margin:
        margin_rows = [('说明', f"基期 {margin['baseline']}%，现期 {margin['current']}%，变化 {margin['delta']} 百分点；方法 {margin['method']}；残差 {margin['residual']} 百分点。数学分解不证明因果。", '', '', '')]
        margin_rows.extend(('因子', f['label'], f['contribution'], '百分点', f.get('contribution_rate')) for f in margin['factors'])
        sheet('净利润率分解', ['类型', '说明或因子', '贡献', '单位', '贡献率'], margin_rows)
    elif snapshot.get('margin_status', {}).get('status') == 'not_applicable':
        sheet('净利润率分解', ['类型', '说明或因子', '贡献', '单位', '贡献率'],
              [('不适用', snapshot['margin_status'].get('reason'), None, '百分点', None)])
    drill = []
    for parent in snapshot.get('drilldown', []):
        drill.append((parent['dimension'], parent['value'], '', '', parent['baseline'], parent['current'], parent['delta']))
        for child in parent.get('children', []):
            drill.append((parent['dimension'], parent['value'], child['dimension'], child['value'],
                          child['baseline'], child['current'], child['delta']))
    sheet('维度下钻', ['一级维度','一级值','二级维度','二级值','基期','现期','差额'], drill)
    trends = sorted(snapshot.get('trends', []), key=lambda point:(point['date'], point['period']))
    if trends:
        sheet('每日趋势', ['日期','比较期','指标值（元）','访问次数','投放费用（元）'],
              [(point['date'], {'baseline':'基期', 'current':'现期'}.get(point['period'], point['period']),
                point['value'], point['visits'], point['spend']) for point in trends])
        chart_sheet = workbook.create_sheet('趋势图')
        chart_sheet.append(['日期', '基期', '现期'])
        try:
            chart_rows = []
            for point in trends:
                day = date.fromisoformat(point['date'])
                value = float(point['value'])
                if day.isoformat() != point['date'] or point['period'] not in ('baseline', 'current') or not isfinite(value):
                    raise ValueError('invalid trend')
                chart_rows.append((point['date'], value if point['period'] == 'baseline' else None,
                                   value if point['period'] == 'current' else None))
            for row in chart_rows:
                chart_sheet.append(row)
            chart = LineChart()
            chart.title = '每日指标趋势（数值为近似展示）'
            chart.y_axis.title = '元'
            chart.x_axis.title = '日期'
            chart.add_data(Reference(chart_sheet, min_col=2, max_col=3, min_row=1, max_row=len(chart_rows)+1), titles_from_data=True)
            chart.set_categories(Reference(chart_sheet, min_col=1, min_row=2, max_row=len(chart_rows)+1))
            chart.display_blanks = 'gap'
            chart_sheet.add_chart(chart, 'E3')
            chart_sheet['E1'] = '图表使用浮点数近似展示；原始精度见“每日趋势”工作表。'
        except (KeyError, TypeError, ValueError, OverflowError):
            chart_sheet['E1'] = '趋势数据无法生成图表；请检查每日趋势工作表。'
    evidence_rows = []
    for candidate in snapshot.get('hypotheses', []):
        initial_count = len(evidence_rows)
        for evidence in candidate.get('evidence', []):
            if evidence.get('kind') != 'descriptive_comparison':
                continue
            for group in evidence['groups']:
                evidence_rows.append((candidate['question'], candidate['status_label'], evidence['dimension'],
                                      group['value'], evidence['metric'], evidence['unit'], group['baseline'],
                                      group['current'], group['delta'], evidence['delta_unit'], evidence['note'],
                                      evidence['total_groups'], '是' if evidence['truncated'] else '否',
                                      '；'.join(candidate.get('required_data', [])), candidate.get('factor_key', '旧记录未保存')))
        if len(evidence_rows) == initial_count:
            evidence_rows.append((candidate['question'], candidate['status_label'], '', '', '', '', None, None,
                                  None, '', '暂无描述性观察', 0, '否', '；'.join(candidate.get('required_data', [])),
                                  candidate.get('factor_key', '旧记录未保存')))
    sheet('候选问题与观察', ['问题','状态','维度','分组','口径','单位','基期','现期','变化','变化单位','限制','分组总数','已截断','所需数据','关联因子键'], evidence_rows)
    sheet('每日均值检验', ['方法','指标','单位','基期样本数','现期样本数','基期均值','现期均值','均值差','t','自由度','p','置信水平','区间下限','区间上限','状态','原因','限制','数据版本','摘要','均值差和区间单位','检验范围','时间 UTC','方法版本','SciPy 版本','候选因子','分组维度','分组值'],
          [(i['method'],i['metric'],i['unit'],i['baseline_n'],i['current_n'],i.get('baseline_mean_decimal') or i['baseline_mean'],i.get('current_mean_decimal') or i['current_mean'],
            i.get('mean_difference_decimal') or i['mean_difference'],i['statistic'],i['degrees_of_freedom'],
            '小于浮点可表示范围' if i.get('p_value_underflow') else i['p_value'],i['confidence_level'],
            (i['interval'] or {}).get('low'),(i['interval'] or {}).get('high'),i['status'],i['reason'],
            '；'.join(i['limitations']),i.get('dataset_version','旧记录未保存'),i.get('data_digest','旧记录未保存'),
            i.get('delta_unit',i['unit']),str(i.get('scope','旧记录未保存')),i.get('calculated_at','旧记录未保存'),
            i.get('method_version','旧记录未保存'),i.get('scipy_version','旧记录未保存'),
            (i['factor_key'] or '整体指标') if 'factor_key' in i else '旧记录未保存',
            i.get('group_dimension') or '未分组',i.get('group_value') or '未分组')
           for i in snapshot.get('statistical_checks', [])])
    event_result = snapshot.get('report_events')
    if event_result:
        count_note = (f"{event_result['notice']} 匹配事件数：{len(event_result['events'])}。"
                      if event_result['status'] == 'available' else event_result['notice'])
        event_rows = [('说明', count_note, event_result['checked_at'], '', '', '', '', '', '')]
        event_rows.extend(('候选关联', item['title'], item['start'], item['end'], str(item['scope']),
                           item['source'], item.get('match_basis', '旧归档未记录匹配依据'), item['evidence_status'], event_result['checked_at'])
                          for item in event_result['events'])
        sheet('事件关联', ['类型','事件或说明','开始或匹配时间','结束','适用范围','来源','匹配依据','证据状态','匹配时间UTC'], event_rows)
    metric = snapshot.get('metric', '指标')
    sheet('情景模拟', ['名称','参数',f'模拟{metric}（元）',f'相对现期{metric}变化（元）','模型假设','收益区间',
                  '模拟净利润率（%）','利润率较现期变化（百分点）','利润率说明'],
          [(i['name'], str(i['changes']), i['prediction'], i['improvement'], i['assumptions'], '暂无依据',
            (i.get('margin') or {}).get('prediction'), (i.get('margin') or {}).get('improvement'),
            (i.get('margin') or {}).get('reason') or ('旧情景未记录，请重新计算' if snapshot.get('scenario_id') == 'consumer' and not i.get('margin') else ''))
           for i in snapshot.get('simulation_scenarios', [])])
    sheet('行动清单', ['动作','关联因子','数学贡献','责任岗位','预计周期天','预计收益元','收益依据','来源'],
          [(i['action'], i['factor_label'], i['factor_contribution'], i['owner_role'] or '待补充',
            i['estimated_days'], i['estimated_benefit'], i['benefit_basis'] or '待补充', '分析师填写')
           for i in snapshot.get('action_items', [])])
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


@lru_cache(maxsize=1)
def _pdf_font():
    configured = os.environ.get('ATTRIBUTION_PDF_FONT_PATH')
    candidates = [configured] if configured else [
        '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
        'C:/Windows/Fonts/simhei.ttf',
    ]
    for path in candidates:
        if path and Path(path).is_file():
            try:
                pdfmetrics.registerFont(TTFont('AttributionCJK', path, subfontIndex=0))
                return 'AttributionCJK'
            except (OSError, ValueError, TTFError):
                continue
    raise RuntimeError('PDF 中文字体不可用，请配置 ATTRIBUTION_PDF_FONT_PATH')


def _trend_drawing(points, font):
    """Plot observed daily points using floating-point approximation, without joining gaps."""
    if not points:
        return None
    try:
        prepared = []
        for point in points:
            day = date.fromisoformat(point['date'])
            value = float(point['value'])
            if day.isoformat() != point['date'] or point['period'] not in ('baseline', 'current') or not isfinite(value):
                return None
            prepared.append((day, point['period'], value))
        if len({(day, period) for day,period,_ in prepared}) != len(prepared):
            return None
    except (KeyError, ValueError, TypeError, OverflowError):
        return None
    min_day, max_day = min(item[0] for item in prepared), max(item[0] for item in prepared)
    low, high = min(item[2] for item in prepared), max(item[2] for item in prepared)
    if low == high:
        padding = abs(low)*0.01 if low else 1.0
        low, high = low-padding, high+padding
    if not isfinite(low) or not isfinite(high) or not isfinite(high-low) or high == low:
        return None
    width, height = 490, 180
    left, right, bottom, top = 90, 475, 32, 145
    drawing = Drawing(width, height)
    drawing.add(Line(left,bottom,right,bottom,strokeColor=colors.HexColor('#8b969c')))
    drawing.add(Line(left,bottom,left,top,strokeColor=colors.HexColor('#8b969c')))
    drawing.add(String(left-5,top-2,format(high,'.5g'),fontName=font,fontSize=7,textAnchor='end'))
    drawing.add(String(left-5,bottom,format(low,'.5g'),fontName=font,fontSize=7,textAnchor='end'))
    drawing.add(String(left,bottom-15,min_day.isoformat(),fontName=font,fontSize=7))
    drawing.add(String(right,bottom-15,max_day.isoformat(),fontName=font,fontSize=7,textAnchor='end'))
    drawing.add(String(left,160,'基期',fontName=font,fontSize=8,fillColor=colors.HexColor('#647b99')))
    drawing.add(String(left+55,160,'现期',fontName=font,fontSize=8,fillColor=colors.HexColor('#087f75')))
    span = max((max_day-min_day).days, 1)
    for period, color in (('baseline','#647b99'),('current','#087f75')):
        series = sorted((day,value) for day,kind,value in prepared if kind == period)
        previous = None
        for day,value in series:
            x = left+(day-min_day).days/span*(right-left)
            y = bottom+(value-low)/(high-low)*(top-bottom)
            if previous and (day-previous[0]).days == 1:
                drawing.add(Line(previous[1],previous[2],x,y,strokeColor=colors.HexColor(color),strokeWidth=1.2))
            drawing.add(Circle(x,y,1.3,fillColor=colors.HexColor(color),strokeColor=None))
            previous = (day,x,y)
    return drawing


def _pdf_number(value):
    """Round for readability without turning a nonzero value into exact zero."""
    original = Decimal(str(value))
    with localcontext() as context:
        context.prec = 80
        result = original.quantize(Decimal('0.000001'))
    if not result and original:
        return format(original, '.6g')
    return format(result, 'f').rstrip('0').rstrip('.') if result else '0'


def pdf(snapshot):
    """Generate a readable, paginated draft using the same Markdown content."""
    font = _pdf_font()
    output = BytesIO()
    document = SimpleDocTemplate(output, pagesize=A4, leftMargin=42, rightMargin=42, topMargin=45, bottomMargin=42,
                                 title='经营归因分析草稿')
    normal = ParagraphStyle('body', fontName=font, fontSize=9, leading=15, wordWrap='CJK', spaceAfter=3)
    heading = ParagraphStyle('heading', parent=normal, fontSize=13, leading=20, textColor=colors.HexColor('#275466'), spaceBefore=8)
    title = ParagraphStyle('title', parent=heading, fontSize=17, leading=25, alignment=TA_CENTER)
    # PDF is a readable view; retain the unrounded strings in Markdown/XLSX.
    printable = deepcopy(snapshot)
    def rounded(container, keys):
        for key in keys:
            value = container.get(key)
            if value is None:
                continue
            try:
                container[key] = _pdf_number(value)
            except (InvalidOperation, ValueError):
                pass
    rounded(printable['breakdown'], ('baseline', 'current', 'delta'))
    for factor in printable['breakdown']['factors']:
        rounded(factor, ('baseline', 'current', 'contribution'))
    for item in printable.get('report_sensitivity', {}).get('rows', []):
        rounded(item, ('current', 'per_unit', 'elasticity'))
    variability = printable.get('report_variability') or {}
    if variability.get('status') == 'available':
        for item in [variability['metric'], *variability['factors']]:
            rounded(item, ('mean', 'stddev', 'relative_percent'))
    if printable.get('margin_breakdown'):
        rounded(printable['margin_breakdown'], ('baseline', 'current', 'delta', 'residual'))
        for factor in printable['margin_breakdown']['factors']:
            rounded(factor, ('contribution',))
    for parent in printable.get('drilldown', []):
        rounded(parent, ('baseline', 'current', 'delta'))
        for child in parent.get('children', []):
            rounded(child, ('baseline', 'current', 'delta'))
    for point in printable.get('trends', []):
        rounded(point, ('value',))
    for candidate in printable.get('hypotheses', []):
        for evidence in candidate.get('evidence', []):
            for group in evidence.get('groups', []):
                rounded(group, ('baseline', 'current', 'delta'))
    for item in printable.get('simulation_scenarios', []):
        rounded(item, ('prediction', 'improvement'))
        if item.get('margin'):
            rounded(item['margin'], ('prediction', 'improvement'))
    for item in printable.get('action_items', []):
        rounded(item, ('factor_contribution', 'estimated_benefit'))
    for item in printable.get('statistical_checks', []):
        rounded(item, ('baseline_mean', 'current_mean', 'mean_difference', 'baseline_mean_decimal', 'current_mean_decimal', 'mean_difference_decimal', 'statistic', 'degrees_of_freedom'))
        if item.get('p_value') is not None:
            item['p_value'] = format(item['p_value'], '.6g')
        if item.get('interval'):
            rounded(item['interval'], ('low', 'high'))
    story = [Paragraph('PDF 数值通常保留 6 位小数；极小非零值使用科学计数法。未舍入数据见 Markdown 或 Excel。', normal)]
    trend_chart = _trend_drawing(snapshot.get('trends', []), font)
    for line in markdown_report_text(printable).splitlines():
        text = line.strip()
        if not text:
            story.append(Spacer(1, 4))
            continue
        if text.startswith('| ---'):
            continue
        style = title if text.startswith('# ') else heading if text.startswith('## ') or text.startswith('### ') else normal
        text = re.sub(r'\\([\\|\[\]()*_`])', r'\1', text.lstrip('# '))
        text = unescape(text)
        story.append(Paragraph(escape(text), style))
        if text == '每日趋势' and snapshot.get('trends'):
            if trend_chart:
                story.append(Paragraph('趋势图为浮点近似展示；未连接缺失日期，精确值见明细。', normal))
                story.append(trend_chart)
            else:
                story.append(Paragraph('趋势数据不适合绘图，请以明细为准。', normal))
    def footer(canvas, doc):
        canvas.setFont(font, 8)
        canvas.drawRightString(A4[0]-42, 25, f'{doc.page}')
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
