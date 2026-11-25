"""Profit margin evidence must survive report export with unambiguous units."""
from io import BytesIO

from openpyxl import load_workbook

from app.domain.scenarios import calculate
from app.domain.exploration import simulate_snapshot
from app.modules.analysis.exporters import spreadsheet
from app.modules.analysis.report import markdown_report_text


def test_consumer_margin_is_exported_with_percentage_and_point_units():
    snapshot = calculate('consumer')
    margin = snapshot['margin_breakdown']
    markdown = markdown_report_text(snapshot)
    assert f"基期：{margin['baseline']}%" in markdown
    assert f"变化：{margin['delta']} 百分点" in markdown
    for factor in margin['factors']:
        assert factor['contribution'] in markdown

    workbook = load_workbook(BytesIO(spreadsheet(snapshot)), data_only=False)
    rows = list(workbook['净利润率分解'].values)
    assert margin['baseline'] in rows[1][1]
    assert rows[2][2] == margin['factors'][0]['contribution']
    assert rows[2][3] == '百分点'


def test_unavailable_margin_reason_survives_reports():
    snapshot = calculate('consumer')
    del snapshot['margin_breakdown']
    snapshot['margin_status'] = {'status': 'not_applicable', 'reason': '基期营收为零，无法计算。'}
    assert '不适用：基期营收为零，无法计算。' in markdown_report_text(snapshot)
    workbook = load_workbook(BytesIO(spreadsheet(snapshot)))
    assert workbook['净利润率分解']['B2'].value == snapshot['margin_status']['reason']


def test_ecommerce_report_does_not_claim_profit_margin():
    snapshot = calculate('ecommerce')
    assert '样例净利润率分解' not in markdown_report_text(snapshot)
    assert '净利润率分解' not in load_workbook(BytesIO(spreadsheet(snapshot))).sheetnames


def test_consumer_simulation_reports_margin_and_zero_revenue_boundaries():
    from decimal import Decimal
    snapshot = calculate('consumer')
    item = simulate_snapshot(snapshot, {'revenue':'1000000', 'material':'500000'})
    assert Decimal(item['prediction']) == Decimal('233000')
    assert Decimal(item['margin']['prediction']) == Decimal('23.3')
    assert abs(Decimal(item['margin']['improvement']) - (Decimal('23.3') - Decimal('14300000') / Decimal('950000'))) < Decimal('1e-24')
    zero = simulate_snapshot(snapshot, {'revenue':'0'})
    assert zero['margin']['prediction'] is None and '模拟营收为零' in zero['margin']['reason']
    snapshot['parameters'] = {**snapshot.get('parameters', {}), **{'revenue':'0','material':'1','logistics':'0','commission':'0','other':'0','tax':'0'}}
    snapshot['breakdown']['current'] = '-1'
    current_zero = simulate_snapshot(snapshot, {'revenue':'100'})
    assert current_zero['margin']['prediction'] is not None and current_zero['margin']['improvement'] is None
    assert '现期营收为零' in current_zero['margin']['reason']


def test_consumer_simulation_margin_is_preserved_in_reports():
    snapshot = calculate('consumer')
    item = simulate_snapshot(snapshot, {'revenue':'1000000', 'material':'500000'})
    snapshot['simulation_scenarios'] = [{'name':'成本方案','changes':{'revenue':'1000000','material':'500000'},**item}]
    report = markdown_report_text(snapshot)
    assert '模拟净利润率（%）' in report and '23.3' in report
    row = list(load_workbook(BytesIO(spreadsheet(snapshot)))['情景模拟'].values)[1]
    assert row[6] == '23.3' and row[7] == item['margin']['improvement']
