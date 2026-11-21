"""PostgreSQL integration only; all provider interactions are mocked."""
import json
import secrets
import unittest
from datetime import timedelta
from decimal import Decimal as D
from unittest.mock import patch
from sqlalchemy import select
import test_api
from app.db import SessionFactory, AnalysisRun, User, BudgetAccount, ModelCall, utcnow
from app.queue import claim, current
from app.worker import process
from app.config import settings
from app import model_gateway


def facts():
    return [dict(date=f'2026-10-0{day}',channel='直播',region='华东',category='食品',segment='新客',
                 visitors='100',orders='5',revenue='1000' if day<=2 else '900',material='500',
                 logistics='100',commission='50',other='80',tax='0',spend='200') for day in range(1,5)]


SCOPE=dict(baseline=['2026-10-01','2026-10-02'],current=['2026-10-03','2026-10-04'],filters={},group_by='channel')


class PipelineTests(unittest.TestCase):
    setUp = test_api.ApiTests.setUp
    tearDown = test_api.ApiTests.tearDown
    authenticate = test_api.ApiTests.authenticate

    def setup_dataset(self):
        result=self.client.post('/api/v1/datasets',json=dict(scenario='ecommerce',name='测试日聚合',format='json',content=json.dumps(facts())))
        self.assertEqual(result.status_code,201,result.text)
        dataset=result.json()['id']
        result=self.client.post('/api/v1/sessions',json=dict(scenario='ecommerce',dataset_id=dataset,scope=SCOPE))
        self.assertEqual(result.status_code,201,result.text)
        return dataset,result.json()['id']

    def submit(self,session,question='只看华东，按品类',key=None,mode='rules'):
        return self.client.post(f'/api/v1/sessions/{session}/runs',json=dict(question=question,request_key=key or secrets.token_hex(16),mode=mode))

    def claim_one(self):
        with SessionFactory.begin() as db:
            task=claim(db)
        self.assertIsNotNone(task)
        return task

    def test_worker_end_to_end_and_replay(self):
        _,session=self.setup_dataset()
        result=self.submit(session)
        self.assertEqual(result.status_code,202,result.text)
        run_id=result.json()['id']
        task=self.claim_one();self.assertEqual(task[0],run_id)
        process(*task)
        run=self.client.get(f'/api/v1/runs/{run_id}').json()
        self.assertEqual(run['status'],'succeeded')
        self.assertEqual(run['result']['scope']['filters'],{'region':'华东'})
        self.assertEqual(run['result']['statistics']['status'],'unavailable')
        snapshot=self.client.get(f'/api/v1/sessions/{session}').json()
        self.assertEqual(snapshot['scope']['group_by'],'category')
        replay=self.client.get(f'/api/v1/runs/{run_id}/events?after=1')
        self.assertNotIn('id: 1\n',replay.text)
        self.assertIn('event: done',replay.text)
        self.assertIn('id: 2',replay.text)

    def test_idempotency_busy_and_cancel(self):
        _,session=self.setup_dataset()
        key=secrets.token_hex(16)
        one=self.submit(session,key=key).json()
        self.assertEqual(self.submit(session,key=key).json()['id'],one['id'])
        self.assertEqual(self.submit(session,question='按区域',key=key).status_code,409)
        self.assertEqual(self.submit(session).status_code,409)
        task=self.claim_one()
        self.assertEqual(self.client.post(f"/api/v1/runs/{one['id']}/cancel").json()['status'],'cancelled')
        process(*task)
        self.assertEqual(self.client.get(f'/api/v1/sessions/{session}').json()['scope'],SCOPE)
        with SessionFactory() as db:
            self.assertIsNone(current(db,*task))
        self.assertEqual(self.submit(session).status_code,202)

    def test_expired_worker_cannot_commit(self):
        _,session=self.setup_dataset()
        self.submit(session)
        old=self.claim_one()
        with SessionFactory.begin() as db:
            db.get(AnalysisRun,old[0]).lease_until=utcnow()-timedelta(seconds=1)
        with SessionFactory() as db:
            self.assertIsNone(current(db,*old))
        new=self.claim_one()
        self.assertEqual(old[0],new[0]);self.assertNotEqual(old[1],new[1])
        process(*old)
        self.assertEqual(self.client.get(f'/api/v1/runs/{old[0]}').json()['status'],'running')
        process(*new)
        self.assertEqual(self.client.get(f'/api/v1/runs/{old[0]}').json()['status'],'succeeded')

    def test_dataset_task_and_stream_ownership(self):
        dataset,session=self.setup_dataset()
        run=self.submit(session).json()['id']
        self.authenticate(self.other.username)
        self.assertEqual(self.client.get('/api/v1/datasets').json(),[])
        self.assertEqual(self.client.post('/api/v1/sessions',json=dict(scenario='ecommerce',dataset_id=dataset,scope=SCOPE)).status_code,404)
        for suffix in ('','/events'):
            self.assertEqual(self.client.get(f'/api/v1/runs/{run}{suffix}').status_code,404)
        self.assertEqual(self.client.post(f'/api/v1/runs/{run}/cancel').status_code,404)

    def test_unknown_question_needs_input_does_not_modify_snapshot(self):
        _,session=self.setup_dataset()
        run=self.submit(session,question='预测明年利润').json()['id']
        process(*self.claim_one())
        self.assertEqual(self.client.get(f'/api/v1/runs/{run}').json()['status'],'needs_input')
        self.assertEqual(self.client.get(f'/api/v1/sessions/{session}').json()['scope'],SCOPE)

    def test_revocation_between_computation_and_commit_discards_result(self):
        from app.domain.exploration import analyze
        _,session=self.setup_dataset()
        run_id=self.submit(session).json()['id']
        task=self.claim_one()
        def revoke_after_compute(*args):
            result=analyze(*args)
            with SessionFactory.begin() as db:
                db.get(User,self.user.id).domains=[]
            return result
        with patch('app.worker.analyze',side_effect=revoke_after_compute):
            process(*task)
        with SessionFactory.begin() as db:
            run=db.get(AnalysisRun,run_id)
            self.assertIsNone(run.result)
            run.lease_until=utcnow()-timedelta(seconds=1)
        with SessionFactory.begin() as db:
            self.assertIsNone(claim(db))
        with SessionFactory() as db:
            self.assertEqual(db.get(AnalysisRun,run_id).status,'failed')

    def test_api_validation_and_duplicate_import(self):
        dataset,_=self.setup_dataset()
        payload=dict(scenario='ecommerce',name='同内容',format='json',content=json.dumps(facts()))
        self.assertEqual(self.client.post('/api/v1/datasets',json=payload).json()['id'],dataset)
        payload['content']=json.dumps(facts()+facts())
        self.assertEqual(self.client.post('/api/v1/datasets',json=payload).status_code,422)
        self.assertEqual(self.client.get('/api/v1/admin/budget').status_code,403)

    def test_budget_unknown_usage_and_cap_are_persistent(self):
        from datetime import date
        from pydantic import SecretStr
        _,session=self.setup_dataset()
        self.submit(session,mode='deepseek')
        run_id,fence=self.claim_one()
        config=settings().model_copy(update=dict(deepseek_key=SecretStr('mock-not-real'),model_price_verified_on=date.today().isoformat(),
                    model_input_cny_per_million=D('1'),model_output_cny_per_million=D('1')))
        with SessionFactory.begin() as db:
            account=db.get(BudgetAccount,'development')
            original=(account.limit_cny,account.spent_cny,account.reserved_cny)
            account.spent_cny,account.reserved_cny=D('0'),D('0')
        try:
            with patch.object(model_gateway,'settings',return_value=config),patch.object(model_gateway,'build_opener') as opener:
                opener.return_value.open.side_effect=TimeoutError('mock timeout')
                with self.assertRaises(ValueError): model_gateway.plan(run_id,fence,'分析',SCOPE,{})
                self.assertEqual(opener.return_value.open.call_count,1)
                with SessionFactory.begin() as db:
                    account=db.get(BudgetAccount,'development')
                    self.assertGreater(account.reserved_cny,0)
                    self.assertEqual(db.scalar(select(ModelCall).where(ModelCall.run_id==run_id)).state,'usage_unknown')
                    account.spent_cny=D('25')
                with self.assertRaisesRegex(ValueError,'MODEL_BUDGET_EXHAUSTED'):
                    model_gateway.plan(run_id,fence,'分析',SCOPE,{})
                self.assertEqual(opener.return_value.open.call_count,1)
        finally:
            with SessionFactory.begin() as db:
                account=db.get(BudgetAccount,'development')
                account.limit_cny,account.spent_cny,account.reserved_cny=original
