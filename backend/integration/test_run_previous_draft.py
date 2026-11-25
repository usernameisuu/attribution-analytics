"""Saved drafts survive a completed follow-up without using a real database."""
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

with patch.dict(os.environ, {'ATTRIBUTION_DATABASE_URL':'postgresql+psycopg://unused@127.0.0.1/unused'}):
    from app.db import AuditEvent, AnalysisRun, AnalysisSession, Base, DatasetVersion, RunEvent, User
    from app.domain.datasets import generate, normalize
    from app.domain.exploration import analyze, default_scope
    from app.domain.scenarios import calculate
    from app.pipeline_api import previous_draft_report, restore_previous_draft, run_info
    from app.worker import process, result_with_previous_drafts


def test_followup_preserves_saved_snapshot_without_attaching_it_to_new_analysis():
    old = calculate('ecommerce')
    old['action_items'] = [{'action':'检查渠道', 'factor_label':'访问次数', 'factor_contribution':'-10',
                            'owner_role':'', 'estimated_days':None, 'estimated_benefit':None, 'benefit_basis':''}]
    new = {'scope':{'filters':{'region':'华东'}}}
    run_result = result_with_previous_drafts(new, old)
    assert run_result['previous_snapshot']['action_items'][0]['action'] == '检查渠道'
    assert 'previous_snapshot' not in new
    assert 'previous_snapshot' not in result_with_previous_drafts(new, calculate('ecommerce'))
    note_only = {**calculate('ecommerce'), 'report_note': {'text':'审核说明'}}
    assert result_with_previous_drafts(new, note_only)['previous_snapshot'] == note_only


def test_worker_authorization_uses_a_postgresql_shared_user_lock():
    from sqlalchemy.dialects import postgresql
    from app.queue import authorized
    user=SimpleNamespace(id='owner',active=True,role='analyst',domains=['ecommerce'])
    dataset=SimpleNamespace(owner_id='owner',scenario='ecommerce')
    class DB:
        def scalar(self, statement):
            assert 'FOR SHARE' in str(statement.compile(dialect=postgresql.dialect()))
            return user
        def get(self, model, key):
            return dataset
    run=SimpleNamespace(owner_id='owner',dataset_id='data')
    assert authorized(DB(),run)
    user.domains=[]
    assert not authorized(DB(),run)


def test_worker_authorization_refreshes_cached_user_before_check():
    from sqlalchemy import update
    from app.queue import authorized
    engine=create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine,tables=[User.__table__,DatasetVersion.__table__])
    with Session(engine,expire_on_commit=False) as db:
        user=User(id='owner',username='owner',password_hash='unused',role='analyst',domains=['ecommerce'],active=True)
        dataset=DatasetVersion(id='data',owner_id='owner',scenario='ecommerce',name='test',source_kind='synthetic',digest='digest',rows=[])
        db.add_all([user,dataset]);db.commit()
        run=SimpleNamespace(owner_id='owner',dataset_id='data')
        assert authorized(db,run)
        db.execute(update(User).where(User.id=='owner').values(domains=[]).execution_options(synchronize_session=False))
        assert user.domains == ['ecommerce']  # The identity map still contains the old grant.
        assert not authorized(db,run)
    engine.dispose()


def test_previous_draft_export_uses_owner_check_and_audits():
    old = calculate('consumer')
    old['simulation_scenarios'] = [{'name':'降成本', 'changes':{'material':'1'}, 'prediction':'2', 'improvement':'3'}]
    run = SimpleNamespace(id='run-1', session_id='session-1', result={'previous_snapshot':old})
    db = SimpleNamespace(added=[], commits=0)
    db.add = db.added.append
    def commit(): db.commits += 1
    db.commit = commit
    user = SimpleNamespace(id='user-1')
    with patch('app.pipeline_api.run_owned', return_value=run) as ownership:
        response = previous_draft_report(run.id, db, user)
        ownership.assert_called_once_with(db, user, run.id)
    assert '降成本' in response.body.decode('utf-8')
    assert '未重新匹配业务事件' in response.body.decode('utf-8')
    assert isinstance(db.added[0], AuditEvent) and db.commits == 1
    run.result = {}
    with patch('app.pipeline_api.run_owned', return_value=run), pytest.raises(HTTPException) as error:
        previous_draft_report(run.id, db, user)
    assert error.value.status_code == 404 and db.commits == 1


def test_worker_persists_previous_draft_and_enforces_real_owner_check(tmp_path):
    # SQLite does not implement PostgreSQL row locks or timezone-aware lease values.
    # Exercise the real worker, ORM and authorization while substituting lease checking.
    engine = create_engine(f"sqlite:///{tmp_path / 'isolated.sqlite'}")
    Base.metadata.create_all(engine, tables=[User.__table__, DatasetVersion.__table__, AnalysisSession.__table__,
                                            AnalysisRun.__table__, RunEvent.__table__, AuditEvent.__table__])
    factory = sessionmaker(engine, expire_on_commit=False)
    rows, digest = normalize(generate('ecommerce'))
    scope = default_scope(rows)
    old = analyze('ecommerce', rows, scope, 'dataset-1')
    old['data_digest'] = digest
    action = {'action':'复核投放', 'factor_label':'访问次数', 'factor_contribution':'-10',
              'owner_role':'', 'estimated_days':None, 'estimated_benefit':None, 'benefit_basis':''}
    with factory.begin() as db:
        db.add_all([
            User(id='owner', username='owner', password_hash='unused', role='analyst', domains=['ecommerce'], active=True),
            User(id='other', username='other', password_hash='unused', role='analyst', domains=['ecommerce'], active=True),
            DatasetVersion(id='dataset-1', owner_id='owner', scenario='ecommerce', name='test', source_kind='synthetic', digest=digest, rows=rows),
            AnalysisSession(id='session-1', owner_id='owner', scenario='ecommerce', title='test', snapshot=old),
            AnalysisRun(id='run-1', session_id='session-1', owner_id='owner', dataset_id='dataset-1',
                        question='只看华东', request_key='test-key', request_hash='hash', scope=scope, parents=[],
                        mode='rules', status='running', stage='planning', fence='test-fence', sequence=0),
        ])
    def current_without_lease(db, run_id, fence):
        run = db.get(AnalysisRun, run_id)
        return run if run and run.status == 'running' and run.fence == fence else None
    def analyze_after_draft_saved(*args):
        result = analyze(*args)
        # Simulate a draft saved after the task started, before the worker commits.
        with factory.begin() as db:
            session = db.get(AnalysisSession, 'session-1')
            session.snapshot = {**session.snapshot, 'action_items':[action]}
        return result
    with patch('app.worker.SessionFactory', factory), patch('app.worker.current', current_without_lease), \
         patch('app.worker.analyze', side_effect=analyze_after_draft_saved):
        process('run-1', 'test-fence')
    with Session(engine) as db:
        run = db.get(AnalysisRun, 'run-1')
        updated = db.get(AnalysisSession, 'session-1')
        assert run.status == 'succeeded' and run_info(run)['has_previous_drafts']
        assert updated.snapshot['scope']['filters'] == {'region':'华东'}
        assert 'action_items' not in updated.snapshot
        assert run.result['previous_snapshot']['action_items'][0]['action'] == '复核投放'
        assert '复核投放' in previous_draft_report('run-1', db, db.get(User, 'owner')).body.decode('utf-8')
        restored = restore_previous_draft('run-1', db, db.get(User, 'owner'))
        assert restored['id'] != 'session-1'
        assert restored['scope'] == scope and restored['action_items'][0]['action'] == '复核投放'
        assert db.get(AnalysisSession, 'session-1').snapshot['scope']['filters'] == {'region':'华东'}
        assert db.get(AnalysisSession, restored['id']).snapshot['action_items'][0]['action'] == '复核投放'
        with pytest.raises(HTTPException) as denied:
            previous_draft_report('run-1', db, db.get(User, 'other'))
        assert denied.value.status_code == 404
        with pytest.raises(HTTPException) as denied_restore:
            restore_previous_draft('run-1', db, db.get(User, 'other'))
        assert denied_restore.value.status_code == 404
        dataset = db.get(DatasetVersion, 'dataset-1')
        dataset.digest = 'changed-digest'
        db.commit()
        with pytest.raises(HTTPException) as mismatch:
            restore_previous_draft('run-1', db, db.get(User, 'owner'))
        assert mismatch.value.status_code == 409
        owner = db.get(User, 'owner')
        owner.domains = []
        db.commit()
        with pytest.raises(HTTPException) as revoked:
            previous_draft_report('run-1', db, owner)
        assert revoked.value.status_code == 403
    engine.dispose()
