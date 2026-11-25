"""Saved drilldown evidence is visible and labeled in report exports."""
from io import BytesIO

from openpyxl import load_workbook

from app.domain.scenarios import calculate
from app.modules.analysis.exporters import spreadsheet
from app.modules.analysis.report import markdown_report_text


def group(value, children=None):
    return {'dimension':'channel', 'value':value, 'baseline':'100', 'current':'80', 'delta':'-20',
            'children':children or []}


def test_report_preserves_parent_child_and_escapes_dimension_values():
    snapshot = calculate('ecommerce')
    child = {'dimension':'region', 'value':'华东|<script>', 'baseline':'100', 'current':'80', 'delta':'-20'}
    snapshot['drilldown'] = [group('自然流量', [child])]
    report = markdown_report_text(snapshot)
    assert '指标：GMV（元）' in report
    assert r'华东\|&lt;script&gt;' in report
    assert '| 渠道 | 自然流量 | 区域 |' in report
    assert '两层数值不能重复相加' in report


def test_markdown_truncation_is_explicit_and_excel_remains_complete():
    snapshot = calculate('consumer')
    snapshot['drilldown'] = [group(f'渠道{i}') for i in range(201)]
    report = markdown_report_text(snapshot)
    assert '仅展示 200 / 201 行' in report
    assert '渠道200' not in report
    sheet = load_workbook(BytesIO(spreadsheet(snapshot)))['维度下钻']
    assert sheet.max_row == 202
    assert sheet.cell(202, 2).value == '渠道200'


def test_fixed_fixture_without_drilldown_does_not_invent_evidence():
    assert '## 维度下钻' not in markdown_report_text(calculate('ecommerce'))
