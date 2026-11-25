import unittest
import warnings
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from app.domain.statistical_checks import daily_welch


def row(day,value):
    return dict(date=f'2026-10-{day:02}',channel='自然流量',region='华东',category='服饰',segment='新客',
                visitors='1',orders='1',revenue=str(value),material='0',logistics='0',commission='0',other='0',tax='0',spend='0')


SCOPE={'baseline':['2026-10-01','2026-10-03'],'current':['2026-10-04','2026-10-06'],
       'filters':{},'group_by':'channel'}


class StatisticalTests(unittest.TestCase):
    def test_welch_known_example_and_assumption_warning(self):
        result=daily_welch('ecommerce',[row(i,i) for i in range(1,7)],SCOPE,0.95)
        self.assertEqual(result['status'],'computed')
        self.assertEqual((result['baseline_n'],result['current_n']),(3,3))
        self.assertEqual(result['mean_difference'],3)
        self.assertAlmostEqual(result['statistic'],3.674234614,places=8)
        self.assertAlmostEqual(result['degrees_of_freedom'],4)
        self.assertAlmostEqual(result['p_value'],0.021311641,places=8)
        self.assertLess(result['interval']['low'],3)
        self.assertGreater(result['interval']['high'],3)
        self.assertTrue(any('自相关' in text for text in result['limitations']))
        self.assertTrue(any('不证明因果' in text for text in result['limitations']))

    def test_insufficient_constant_and_precision_loss_are_not_successes(self):
        single=dict(SCOPE,baseline=['2026-10-01','2026-10-01'],current=['2026-10-02','2026-10-02'])
        self.assertEqual(daily_welch('ecommerce',[row(1,1),row(2,2)],single,0.95)['status'],'not_applicable')
        self.assertEqual(daily_welch('ecommerce',[row(i,10 if i<4 else 20) for i in range(1,7)],SCOPE,0.95)['status'],'not_applicable')
        values=['10000000000000001','10000000000000002','10000000000000003','1','2','3']
        result=daily_welch('ecommerce',[row(i,value) for i,value in enumerate(values,1)],SCOPE,0.95)
        self.assertEqual(result['status'],'not_applicable')
        self.assertIn('精度',result['reason'])
        self.assertIsNone(result['p_value'])

    def test_p_value_underflow_is_not_presented_as_exact_zero(self):
        fake=SimpleNamespace(statistic=1000.0,df=4.0,pvalue=0.0,
                             confidence_interval=lambda confidence_level:SimpleNamespace(low=2.0,high=4.0))
        with patch('app.domain.statistical_checks.ttest_ind',return_value=fake):
            result=daily_welch('ecommerce',[row(i,i) for i in range(1,7)],SCOPE,0.95)
        self.assertEqual(result['status'],'computed')
        self.assertIsNone(result['p_value'])
        self.assertTrue(result['p_value_underflow'])

    def test_large_aggregates_with_tiny_daily_gaps_use_centered_values(self):
        rows=[]
        increments=['0','0.125','0.125','0.125','0.250','0.250']
        for day, increment in enumerate(increments,1):
            for index in range(1000):
                amount = '1000000000000' if index < 999 else str(Decimal('999999999999')+Decimal(increment))
                rows.append(dict(row(day,amount),category=f'品类{index}'))
        result=daily_welch('ecommerce',rows,SCOPE,0.95)
        self.assertEqual(result['status'],'computed')
        self.assertAlmostEqual(result['statistic'],2.12132034356,places=9)
        self.assertAlmostEqual(result['p_value'],0.1011915072,places=9)
        self.assertEqual(Decimal(result['mean_difference_decimal']),Decimal('0.125'))
        self.assertIsNone(result['baseline_mean'])
        self.assertTrue(result['baseline_mean_decimal'].startswith('999999999999999.'))
        from io import BytesIO
        from openpyxl import load_workbook
        from app.domain.scenarios import calculate
        from app.modules.analysis.report import statistical_section
        from app.modules.analysis.exporters import spreadsheet
        result.update(dataset_version='test-data',data_digest='test-digest',method_version='daily-welch-v5')
        text='\n'.join(statistical_section([result]))
        self.assertIn(result['baseline_mean_decimal'],text)
        self.assertIn('Decimal 80 位精度',text)
        snapshot=calculate('ecommerce'); snapshot['statistical_checks']=[result]
        page=load_workbook(BytesIO(spreadsheet(snapshot)),data_only=False)['每日均值检验']
        headers={cell.value:cell.column for cell in page[1]}
        self.assertEqual(page.cell(2,headers['基期均值']).value,result['baseline_mean_decimal'])
        self.assertEqual(page.cell(2,headers['均值差']).value,result['mean_difference_decimal'])

    def test_scipy_runtime_warning_does_not_produce_a_success(self):
        def warned(*args, **kwargs):
            warnings.warn('precision warning',RuntimeWarning)
            return SimpleNamespace(statistic=1,df=4,pvalue=.3,
                                   confidence_interval=lambda confidence_level:SimpleNamespace(low=-1,high=2))
        with patch('app.domain.statistical_checks.ttest_ind',side_effect=warned):
            result=daily_welch('ecommerce',[row(i,i) for i in range(1,7)],SCOPE,0.95)
        self.assertEqual(result['status'],'not_applicable')
        self.assertIn('数值精度警告',result['reason'])
        self.assertIsNone(result['p_value'])

    def test_candidate_daily_ratio_uses_daily_values_and_identifies_limits(self):
        rows = [dict(row(i,i), visitors='100', orders=str(i)) for i in range(1,7)]
        result = daily_welch('ecommerce', rows, SCOPE, 0.95, 'conversion')
        self.assertEqual(result['status'], 'computed')
        self.assertEqual(result['factor_key'], 'conversion')
        self.assertAlmostEqual(result['mean_difference'], 0.03)
        self.assertAlmostEqual(result['p_value'], 0.021311641, places=8)
        self.assertTrue(any('逐日比率的简单均值' in item for item in result['limitations']))
        self.assertTrue(any('不能确认或排除' in item for item in result['limitations']))

    def test_candidate_zero_denominator_and_wrong_scenario_fail_safely(self):
        rows = [dict(row(i,i), visitors='100', orders=str(i)) for i in range(1,7)]
        rows[1].update(visitors='0',orders='0',revenue='0')
        result = daily_welch('ecommerce', rows, SCOPE, 0.95, 'conversion')
        self.assertEqual(result['status'], 'not_applicable')
        self.assertIn('分母为零', result['reason'])
        self.assertIsNone(result['p_value'])
        with self.assertRaisesRegex(ValueError, '不支持'):
            daily_welch('ecommerce', rows, SCOPE, 0.95, 'material')

    def test_candidate_ratio_tiny_variation_uses_centered_values(self):
        rows = [row(i, '1.' + '0'*19 + str(i)) for i in range(1,7)]
        result = daily_welch('ecommerce', rows, SCOPE, 0.95, 'basket')
        self.assertEqual(result['status'], 'computed')
        self.assertAlmostEqual(result['statistic'], 3.674234614, places=8)
        self.assertIsNone(result['baseline_mean'])
        self.assertEqual(Decimal(result['mean_difference_decimal']),Decimal('3e-20'))

    def test_cost_rate_difference_uses_percentage_points(self):
        rows = [dict(row(i,100), material=str(i)) for i in range(1,7)]
        result = daily_welch('consumer', rows, SCOPE, 0.95, 'material')
        self.assertEqual(result['status'], 'computed')
        self.assertEqual(result['unit'], '%')
        self.assertEqual(result['delta_unit'], '百分点')
        self.assertAlmostEqual(result['mean_difference'], 3)

    def test_group_gap_compares_daily_group_to_rest_between_periods(self):
        rows=[]
        for i in range(1,7):
            group_orders = i + (9 if i <= 3 else 16)
            rows.append(dict(row(i,100),channel='A',visitors='100',orders=str(group_orders)))
            rows.append(dict(row(i,100),channel='B',visitors='100',orders='5'))
        result=daily_welch('ecommerce',rows,SCOPE,0.95,'conversion','A')
        self.assertEqual(result['status'],'computed')
        self.assertEqual(result['group_dimension'],'channel')
        self.assertEqual(result['group_value'],'A')
        self.assertAlmostEqual(result['baseline_mean'],0.06)
        self.assertAlmostEqual(result['current_mean'],0.16)
        self.assertAlmostEqual(result['mean_difference'],0.1)
        self.assertTrue(any('未控制混杂' in limitation for limitation in result['limitations']))

    def test_group_gap_rejects_missing_comparison_or_zero_denominator(self):
        rows=[]
        for i in range(1,7):
            rows.append(dict(row(i,100),channel='A',visitors='100',orders=str(i)))
            rows.append(dict(row(i,100),channel='B',visitors='100',orders='2'))
        with self.assertRaises(ValueError):
            daily_welch('ecommerce',rows,SCOPE,0.95,'conversion','不存在')
        with self.assertRaises(ValueError):
            daily_welch('ecommerce',rows,dict(SCOPE,filters={'channel':'A'}),0.95,'conversion','A')
        rows[1].update(visitors='0',orders='0',revenue='0')
        result=daily_welch('ecommerce',rows,SCOPE,0.95,'conversion','A')
        self.assertEqual(result['status'],'not_applicable')
        self.assertIn('分母为零',result['reason'])

    def test_group_cost_rate_gap_unit_is_percentage_points(self):
        rows=[]
        for i in range(1,7):
            rows.append(dict(row(i,100),category='A',material=str(i)))
            rows.append(dict(row(i,100),category='B',material='1'))
        result=daily_welch('consumer',rows,SCOPE,0.95,'material','A')
        self.assertEqual(result['unit'],'百分点')
        self.assertEqual(result['delta_unit'],'百分点')
        self.assertAlmostEqual(result['mean_difference'],3)
