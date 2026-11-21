import copy
import json
import unittest
from decimal import Decimal as D
from app.domain.datasets import normalize, parse_upload, generate
from app.domain.exploration import validate_scope, rule_plan, analyze, simulate_snapshot
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

    def test_json_decimal_avoids_float_rounding(self):
        payload=json.dumps(facts()).replace('"500"','500.123456789123456789')
        self.assertEqual(parse_upload(payload,'json')[0][0]['material'],'500.123456789123456789')

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
    def test_real_totals_and_drilldown_conserve(self):
        snapshot=analyze('ecommerce',facts(),SCOPE,'version-1')
        self.assertEqual(D(snapshot['breakdown']['baseline']),4000)
        self.assertEqual(D(snapshot['breakdown']['current']),2880)
        self.assertEqual(sum(D(r['delta']) for r in snapshot['drilldown']),D(snapshot['breakdown']['delta']))
        self.assertLess(abs(D(snapshot['breakdown']['residual'])),D('1e-15'))
        self.assertEqual(snapshot['dataset_version'],'version-1')

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

    def test_consumer_margins_and_selected_scope(self):
        snapshot=analyze('consumer',facts(),dict(SCOPE,filters={'channel':'自然流量'}),'v')
        self.assertEqual(D(snapshot['breakdown']['current']),-20)
        self.assertLess(abs(D(snapshot['margin_breakdown']['residual'])),D('1e-15'))
        self.assertEqual(len(snapshot['drilldown']),1)


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
