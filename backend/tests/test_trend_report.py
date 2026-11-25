from io import BytesIO
from datetime import date, timedelta

from openpyxl import load_workbook

from app.domain.scenarios import calculate
from app.modules.analysis.exporters import _pdf_number, _trend_drawing, spreadsheet
from app.modules.analysis.report import markdown_report_text


def test_daily_trend_has_full_precision_data_and_separate_approximate_chart():
    snapshot = calculate('ecommerce')
    snapshot['trends'] = [
        {'date':'2026-10-02', 'period':'current', 'value':'123.123456789123456789', 'visits':'10', 'spend':'1'},
        {'date':'2026-10-01', 'period':'baseline', 'value':'100.000000000000000001', 'visits':'9', 'spend':'2'},
    ]
    report = markdown_report_text(snapshot)
    assert '| 2026-10-01 | 基期 | 100.000000000000000001 |' in report
    workbook = load_workbook(BytesIO(spreadsheet(snapshot)))
    assert workbook['每日趋势']['C2'].value == '100.000000000000000001'
    assert workbook['每日趋势']['C2'].data_type == 's'
    assert len(workbook['趋势图']._charts) == 1
    assert '近似展示' in workbook['趋势图']['E1'].value
    assert workbook['趋势图']['B2'].value == 100.0
    assert workbook['趋势图']['C3'].value == 123.1234567891235


def test_trend_text_discloses_truncation_and_fixed_fixture_does_not_invent_data():
    snapshot = calculate('consumer')
    assert '## 每日趋势' not in markdown_report_text(snapshot)
    snapshot['trends'] = [{'date':(date(2026,1,1)+timedelta(days=i)).isoformat(), 'period':'baseline', 'value':'1', 'visits':'1', 'spend':'0'}
                          for i in range(121)]
    assert '仅展示 120 / 121 行' in markdown_report_text(snapshot)


def test_pdf_plot_keeps_missing_days_and_comparison_periods_disconnected():
    points = [{'date':'2026-10-01','period':'baseline','value':'1'},
              {'date':'2026-10-03','period':'baseline','value':'2'},
              {'date':'2026-10-04','period':'current','value':'3'}]
    drawing = _trend_drawing(points, 'Helvetica')
    from reportlab.graphics.shapes import Line
    # Only the two axes remain: neither a gap nor different periods are joined.
    assert len([shape for shape in drawing.contents if isinstance(shape, Line)]) == 2
    assert _trend_drawing(points+[points[0]], 'Helvetica') is None
    assert _trend_drawing([{**points[0], 'value':'NaN'}], 'Helvetica') is None


def test_pdf_retains_nonzero_tiny_values_and_sensible_constant_axis():
    assert _pdf_number('0') == '0'
    assert _pdf_number('0.00000001') == '1e-8'
    assert _pdf_number('-0.00000001') == '-1e-8'
    from reportlab.graphics.shapes import String
    drawing = _trend_drawing([{'date':'2026-10-01','period':'baseline','value':'0.000001'}], 'Helvetica')
    labels = [shape.text for shape in drawing.contents if isinstance(shape, String)]
    assert '1.01e-06' in labels and '9.9e-07' in labels
