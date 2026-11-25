from decimal import Decimal

from app.domain.scenarios import calculate
from app.domain.sensitivity import capture_formula_sensitivity, formula_sensitivity


def test_gmv_sensitivity_is_formula_derived_at_current_factors():
    result = formula_sensitivity(calculate('ecommerce'))
    rows = {row['key']:row for row in result['rows']}
    assert Decimal(rows['visitors']['per_unit']) == Decimal('5.4')
    assert Decimal(rows['conversion']['per_unit']) == Decimal('21600000')
    assert Decimal(rows['basket']['per_unit']) == Decimal('3600')
    assert all(Decimal(row['elasticity']) == 1 for row in rows.values())
    assert '不是历史估计、因果效应' in result['notice']


def test_profit_sensitivity_signs_and_zero_factors():
    snapshot = calculate('consumer')
    result = formula_sensitivity(snapshot)
    rows = {row['key']:row for row in result['rows']}
    assert Decimal(rows['revenue']['per_unit']) == 1
    assert Decimal(rows['material']['per_unit']) == -1
    assert rows['tax']['elasticity'] is None and rows['tax']['reason'] == '现期因子为零'
    snapshot['breakdown']['current'] = '0'
    result = formula_sensitivity(snapshot)
    assert all(row['elasticity'] is None for row in result['rows'])
    assert '现期指标为零' in result['zero_metric_notice']


def test_old_dataset_snapshot_without_parameters_is_not_replaced_by_fixture_values():
    snapshot = calculate('ecommerce')
    snapshot['dataset_version'] = 'old-import'
    assert capture_formula_sensitivity(snapshot)['status'] == 'unavailable'
