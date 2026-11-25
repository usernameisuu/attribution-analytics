import copy
import json
import unittest
from decimal import Decimal as D
from app.domain.datasets import normalize, parse_upload, generate
from app.domain.exploration import validate_scope, rule_plan, analyze, simulate_snapshot, group_totals
from app.domain.budget import reserve_cost


def facts():
    return [dict(date=f'2026-10-0{day}',channel=channel,region='华东',category='服饰',segment='新客',
                 visitors='100',orders='5' if day<=2 else '4',revenue='1000' if day<=2 else '720',
                 material='500',logistics='100',commission='50',other='80',tax='0',spend='200')
            for day in range(1,5) for channel in ('自然流量','付费投放')]


SCOPE = dict(baseline=['2026-10-01','2026-10-02'],current=['2026-10-03','2026-10-04'],filters={},group_by='channel')


class DatasetTests(unittest.TestCase):
    def test_canonical_digest_and_nonmutating(self):
        raw=facts()
        rows,digest=normalize(raw)
        self.assertEqual(digest,normalize(list(reversed(raw)))[1])
        self.assertEqual(rows,parse_upload(json.dumps(raw),'json')[0])
        self.assertEqual(raw,facts())

    def test_duplicate_missing_and_nonfinite(self):
        cases=[facts()+[facts()[0]],facts()[1:]]
        for field,value in [('visitors','1.2'),('revenue','NaN'),('material','-1'),('region',None),('orders','Infinity')]:
            rows=facts();rows[0][field]=value;cases.append(rows)
        for rows in cases:
            with self.subTest(rows=rows[0]):
                with self.assertRaises(ValueError): normalize(rows)

    def test_csv_duplicate_headers_rejected(self):
        with self.assertRaises(ValueError): parse_upload('date,date\n2026-10-01,2026-10-02','csv')

    def test_json_duplicate_fields_are_rejected_before_values_are_overwritten(self):
        payload = json.dumps(facts()).replace('"revenue": "1000"', '"revenue": "1000", "revenue": "1"', 1)
        with self.assertRaisesRegex(ValueError, '重复字段'):
            parse_upload(payload, 'json')

    def test_json_decimal_avoids_float_rounding(self):
        payload=json.dumps(facts()).replace('"500"','500.123456789123456789')
        self.assertEqual(parse_upload(payload,'json')[0][0]['material'],'500.123456789123456789')

    def test_rejects_unsupported_fractional_precision(self):
        rows=facts(); rows[0]['material']='0.' + '0'*36 + '1'
        with self.assertRaisesRegex(ValueError, '36 位有效小数'):
            normalize(rows)

    def test_gap_and_inconsistent_orders(self):
        with self.assertRaises(ValueError): normalize([r for r in facts() if r['date']!='2026-10-02'])
        rows=facts();rows[0]['visitors']='0'
        with self.assertRaises(ValueError): normalize(rows)

    def test_generated_data_complete_reproducible(self):
        first=generate('ecommerce')
        self.assertEqual(len(first),8640)
        self.assertEqual(first,generate('ecommerce'))
        self.assertEqual(len({r['date'] for r in first}),90)


class ExplorationTests(unittest.TestCase):
    def test_high_precision_amounts_remain_exact_in_totals_and_analysis(self):
        rows=facts()
        for row in rows:
            row['revenue']='123456789012.123456789123456789'
        rows,_=normalize(rows)
        result=analyze('ecommerce', rows, SCOPE, 'v')
        self.assertEqual(D(result['breakdown']['baseline']), D('493827156048.493827156493827156'))
        self.assertEqual(result['algorithm_version'], 'decimal-v4')
        self.assertTrue(all(item['baseline'] == '246913578024.246913578246913578' for item in result['drilldown']))

    def test_36_decimal_revenue_total_is_not_reconstructed_from_rounded_ratios(self):
        rows=facts()
        for row in rows:
            row['revenue']='123456789012.123456789123456789123456789123456789'
        rows,_=normalize(rows)
        result=analyze('ecommerce', rows, SCOPE, 'v')
        self.assertEqual(D(result['breakdown']['baseline']),
                         D('493827156048.493827156493827156493827156493827156'))
        self.assertEqual(D(result['breakdown']['baseline']), D(result['breakdown']['current']))

    def test_unchanged_simulation_reproduces_observed_high_precision_total(self):
        rows=facts()
        for row in rows:
            row.update(visitors='17', orders='7', revenue='123456789012.123456789123456789123456789123456789')
        rows,_=normalize(rows)
        snapshot=analyze('ecommerce', rows, SCOPE, 'v')
        unchanged=simulate_snapshot(snapshot, {'visitors':snapshot['parameters']['visitors']})
        self.assertEqual(D(unchanged['prediction']), D(snapshot['breakdown']['current']))
        self.assertEqual(D(unchanged['improvement']), D(0))

    def test_calculated_current_factors_can_be_retained_beyond_input_precision(self):
        rows=facts()
        for row in rows:
            row.update(visitors='17', orders='7', revenue='100')
        rows,_=normalize(rows)
        snapshot=analyze('ecommerce', rows, SCOPE, 'v')
        conversion=snapshot['parameters']['conversion']
        self.assertGreater(len(conversion.split('.')[1]), 36)
        same=simulate_snapshot(snapshot, {'conversion':conversion, 'visitors':snapshot['parameters']['visitors']})
        self.assertEqual(D(same['improvement']), D(0))
        changed=simulate_snapshot(snapshot, {'conversion':conversion, 'visitors':'100'})
        self.assertEqual(changed['parameters']['conversion'], conversion)
        with self.assertRaisesRegex(ValueError, '36 位有效小数'):
            simulate_snapshot(snapshot, {'conversion':'0.' + '0'*36 + '1'})

    def test_group_totals_aggregates_each_row_once(self):
        class CountingRows:
            def __init__(self, rows):
                self.rows, self.yielded = rows, 0
            def __iter__(self):
                for row in self.rows:
                    self.yielded += 1
                    yield row
        rows=CountingRows(facts())
        grouped=group_totals(rows,'channel')
        self.assertEqual(rows.yielded,len(facts()))
        self.assertEqual(grouped['自然流量']['revenue'],D('3440'))
        self.assertEqual(grouped['付费投放']['orders'],D('18'))

    def test_real_totals_and_drilldown_conserve(self):
        snapshot=analyze('ecommerce',facts(),SCOPE,'version-1')
        self.assertEqual(D(snapshot['breakdown']['baseline']),4000)
        self.assertEqual(D(snapshot['breakdown']['current']),2880)
        self.assertEqual(sum(D(r['delta']) for r in snapshot['drilldown']),D(snapshot['breakdown']['delta']))
        self.assertLess(abs(D(snapshot['breakdown']['residual'])),D('1e-15'))
        self.assertEqual(snapshot['dataset_version'],'version-1')
        self.assertEqual(snapshot['metric_definition_version'],'sample-metrics-v1')

    def test_daily_trend_matches_scoped_totals_in_both_scenarios(self):
        for scenario in ('ecommerce', 'consumer'):
            with self.subTest(scenario=scenario):
                scope=dict(SCOPE,filters={'channel':'自然流量'})
                snapshot=analyze(scenario,facts(),scope,'version-1')
                for period,expected in (('baseline','baseline'),('current','current')):
                    daily=[point for point in snapshot['trends'] if point['period']==period]
                    self.assertEqual(len(daily),2)
                    self.assertEqual(sum(D(point['value']) for point in daily),D(snapshot['breakdown'][expected]))
                    self.assertEqual([point['date'] for point in daily], sorted(point['date'] for point in daily))

    def test_candidate_questions_link_to_calculation_without_claiming_validation(self):
        for scenario, expected in (('ecommerce',3),('consumer',4)):
            with self.subTest(scenario=scenario):
                snapshot=analyze(scenario,facts(),SCOPE,'dataset-v1')
                factors={factor['key']:factor for factor in snapshot['breakdown']['factors']}
                self.assertEqual(len(snapshot['hypotheses']),expected)
                self.assertEqual(len({item['id'] for item in snapshot['hypotheses']}),expected)
                for item in snapshot['hypotheses']:
                    self.assertEqual(item['status'],'pending')
                    self.assertEqual(item['source'],'rule')
                    self.assertEqual(item['evidence'][0]['kind'],'descriptive_comparison')
                    self.assertEqual(item['factor_contribution'],factors[item['factor_key']]['contribution'])
                    self.assertGreaterEqual(len(item['required_data']),2)
                    self.assertNotIn('confidence',item)
        filtered=analyze('ecommerce',facts(),dict(SCOPE,filters={'channel':'自然流量'}),'dataset-v1')
        original=analyze('ecommerce',facts(),SCOPE,'dataset-v1')
        self.assertNotEqual(filtered['hypotheses'][1]['factor_contribution'], original['hypotheses'][1]['factor_contribution'])

    def test_descriptive_evidence_uses_ratio_of_totals_and_flags_zero_denominator(self):
        rows=facts()
        for row in rows:
            if row['channel']=='付费投放' and row['date'] >= '2026-10-03':
                row['visitors']=row['orders']=row['revenue']='0'
        rows,_=normalize(rows)
        snapshot=analyze('ecommerce',rows,SCOPE,'v')
        conversion=next(item for item in snapshot['hypotheses'] if item['factor_key']=='conversion')['evidence'][0]
        groups={group['value']:group for group in conversion['groups']}
        self.assertEqual(D(groups['自然流量']['baseline']),D('0.05'))
        self.assertEqual(D(groups['自然流量']['current']),D('0.04'))
        self.assertIsNone(groups['付费投放']['current'])
        self.assertIsNone(groups['付费投放']['delta'])
        self.assertEqual(snapshot['hypotheses'][1]['status'],'pending')

    def test_consumer_descriptive_cost_rate_uses_percent_and_percentage_points(self):
        snapshot=analyze('consumer',facts(),SCOPE,'v')
        evidence=next(item for item in snapshot['hypotheses'] if item['factor_key']=='material')['evidence'][0]
        self.assertEqual(evidence['unit'],'%')
        self.assertEqual(evidence['delta_unit'],'百分点')
        self.assertEqual(D(evidence['groups'][0]['baseline']),D('50'))
        self.assertEqual(evidence['dimension'],'category')

    def test_two_level_drilldown_totals_and_filters(self):
        rows=facts()
        rows += [dict(row,region='华南',revenue=str(D(row['revenue'])*2)) for row in facts()]
        rows,_=normalize(rows)
        for scenario in ('ecommerce','consumer'):
            for group_by in ('channel','region'):
                with self.subTest(scenario=scenario,group_by=group_by):
                    snapshot=analyze(scenario,rows,dict(SCOPE,group_by=group_by),'v')
                    for parent in snapshot['drilldown']:
                        self.assertEqual(len(parent['children']),2)
                        for key in ('baseline','current','delta'):
                            self.assertEqual(sum(D(child[key]) for child in parent['children']),D(parent[key]))
                    self.assertEqual(sum(D(parent['delta']) for parent in snapshot['drilldown']),D(snapshot['breakdown']['delta']))
            scoped=analyze(scenario,rows,dict(SCOPE,filters={'region':'华南'}),'v')
            self.assertTrue(all(len(parent['children'])==1 and parent['children'][0]['value']=='华南' for parent in scoped['drilldown']))

    def test_multiturn_preserves_and_clears_scope(self):
        first=rule_plan('只看华东，按渠道',SCOPE,facts(),[])
        second=rule_plan('只看服饰，按品类',first,facts(),[SCOPE])
        self.assertEqual(second['filters'],dict(region='华东',category='服饰'))
        third=rule_plan('返回全国',second,facts(),[SCOPE,first])
        self.assertEqual(third['filters'],dict(category='服饰'))
        self.assertEqual(rule_plan('返回上一级',second,facts(),[SCOPE,first]),first)
        self.assertEqual(SCOPE['filters'],{})

    def test_unknown_and_negative_intents_are_not_silently_ignored(self):
        for question in ('不要看华东','华东 2026-10-08','预测明年收入','自然流量或付费投放'):
            with self.subTest(question=question):
                with self.assertRaises(ValueError): rule_plan(question,SCOPE,facts(),[])

    def test_invalid_scopes_rejected(self):
        cases=[None,[],{},dict(SCOPE,group_by=['channel']),dict(SCOPE,filters={'secret':'x'}),
               dict(SCOPE,current=['2026-10-02','2026-10-03']),dict(SCOPE,current=['2026-10-04','2026-10-04']),
               dict(SCOPE,current=['2026-10-05','2026-10-06']),dict(SCOPE,current=['20261003','20261004'])]
        for scope in cases:
            with self.subTest(scope=scope):
                with self.assertRaises(ValueError): validate_scope(scope,facts())

    def test_simulation_uses_snapshot_and_leaves_it_immutable(self):
        snapshot=analyze('ecommerce',facts(),SCOPE,'private-data')
        original=copy.deepcopy(snapshot)
        result=simulate_snapshot(snapshot,{'conversion':'0.05'})
        self.assertEqual(D(result['prediction']),3600)
        self.assertEqual(D(result['improvement']),720)
        self.assertEqual(snapshot,original)

    def test_missing_dataset_parameters_do_not_fall_back_to_fixture(self):
        snapshot=analyze('ecommerce',facts(),SCOPE,'private-data')
        del snapshot['parameters']
        with self.assertRaisesRegex(ValueError, '未记录模拟参数'):
            simulate_snapshot(snapshot, {'conversion':'0.05'})

    def test_consumer_margins_and_selected_scope(self):
        snapshot=analyze('consumer',facts(),dict(SCOPE,filters={'channel':'自然流量'}),'v')
        self.assertEqual(D(snapshot['breakdown']['current']),-20)
        self.assertLess(abs(D(snapshot['margin_breakdown']['residual'])),D('1e-15'))
        self.assertEqual(len(snapshot['drilldown']),1)
        self.assertEqual(snapshot['margin_status']['status'],'available')
        self.assertIn('仅扣除原材料', snapshot['gross_margin_definition'])

    def test_zero_revenue_preserves_profit_analysis_without_inventing_margin(self):
        for zero_period in ('baseline', 'current', 'both'):
            with self.subTest(zero_period=zero_period):
                rows=facts()
                for row in rows:
                    is_baseline=row['date'] <= '2026-10-02'
                    if zero_period == 'both' or (zero_period == 'baseline') == is_baseline:
                        row['visitors']=row['orders']=row['revenue']='0'
                rows,_=normalize(rows)
                snapshot=analyze('consumer',rows,SCOPE,'zero-revenue')
                self.assertEqual(snapshot['margin_status']['status'],'not_applicable')
                self.assertIn('营收为零',snapshot['margin_status']['reason'])
                self.assertNotIn('margin_breakdown',snapshot)
                self.assertNotIn('dimension_margin',snapshot)
                self.assertIsNone(snapshot['gross_margin']['baseline' if zero_period != 'current' else 'current'])
                self.assertEqual(sum(D(cell['delta']) for cell in snapshot['drilldown']),D(snapshot['breakdown']['delta']))
                if zero_period != 'baseline':
                    simulated=simulate_snapshot(snapshot,{'material':'1000'})
                    self.assertEqual(D(simulated['prediction']),-1920)


class BudgetTests(unittest.TestCase):
    def test_unverified_or_nonfinite_prices_rejected(self):
        for rate in ('0','-1','NaN','Infinity'):
            with self.assertRaises(ValueError): reserve_cost([],D(rate),D(1))

    def test_utf8_reservation_grows_and_rounds_up(self):
        small=reserve_cost([{'content':'中'}],D(2),D(3))
        large=reserve_cost([{'content':'中文'*100}],D(2),D(3))
        self.assertGreater(large,small)
        self.assertGreater(small,D(2048)*D(3)/D(1000000))


if __name__=='__main__':
    unittest.main()
