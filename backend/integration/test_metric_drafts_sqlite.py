"""Metric draft validation and persistence without PostgreSQL or HTTP."""
import os
from copy import deepcopy
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

with patch.dict(os.environ, {'ATTRIBUTION_DATABASE_URL':'postgresql+psycopg://unused@127.0.0.1/unused'}):
    from app.db import AuditEvent, Base, MetricDraft, User
    from app.domain.metric_catalog import catalog
    from app.modules.analysis.metric_drafts_api import MetricDraftInput, MetricPreviewInput, SyntheticComparisonInput, compare_draft_synthetic, comparison_history, create_draft, get_draft, list_drafts, preview_draft, template


def test_immutable_draft_versions_are_validated_persisted_and_admin_only():
    engine=create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine,tables=[User.__table__,MetricDraft.__table__,AuditEvent.__table__])
    with Session(engine,expire_on_commit=False) as db:
        admin=User(id='admin',username='admin',password_hash='unused',role='admin',domains=[],active=True)
        analyst=User(id='analyst',username='analyst',password_hash='unused',role='analyst',domains=['ecommerce'],active=True)
        db.add_all([admin,analyst]);db.commit()
        definitions=template('ecommerce',admin)['definitions']
        original=deepcopy(definitions)
        first=create_draft(MetricDraftInput(scenario='ecommerce',name=' 初版 ',definitions=definitions),db,admin)
        assert first['status']=='draft' and first['name']=='初版'
        definitions['visits']['unit']={'visit':2}
        assert get_draft(first['id'],db,admin)['definitions']==original
        second=create_draft(MetricDraftInput(scenario='ecommerce',name='第二版',definitions=original),db,admin)
        assert second['id']!=first['id'] and second['digest']==first['digest']
        assert len(list_drafts(db,admin,'ecommerce'))==2
        assert list_drafts(db,admin,'consumer')==[]
        assert len(db.scalars(select(AuditEvent).where(AuditEvent.action=='metric_draft_created')).all())==2
        inputs={'visits':'100000','orders':'5000','sales_amount':'1000000'}
        preview=preview_draft(first['id'],MetricPreviewInput(target='gmv_from_factors',inputs=inputs),db,admin)
        assert preview['value']=='1000000.00' and preview['unit']=={'cny':1}
        assert '不启用草稿' in preview['notice']
        audit=db.scalars(select(AuditEvent).where(AuditEvent.action=='metric_draft_previewed')).one()
        assert audit.details=={'digest':first['digest'],'target':'gmv_from_factors'}
        comparison=compare_draft_synthetic(first['id'],SyntheticComparisonInput(target='gmv_from_factors'),db,admin)
        assert comparison['draft_digest']==first['digest'] and len(comparison['periods'])==2
        event=db.scalars(select(AuditEvent).where(AuditEvent.action=='metric_draft_synthetic_compared')).one()
        assert event.details['data_digest']==comparison['data_digest']
        history=comparison_history(first['id'],db,admin)
        assert len(history)==1 and history[0]['status']=='available'
        assert history[0]['result']['periods']==comparison['periods']
        intact=deepcopy(event.details)
        for field in ('target', 'data_digest'):
            changed=deepcopy(intact);changed[field]='wrong'
            event.details=changed;db.commit()
            item=comparison_history(first['id'],db,admin)[0]
            assert item['status']=='corrupt' and item['result'] is None
        for field in ('comparison', 'result_digest'):
            changed=deepcopy(intact);del changed[field]
            event.details=changed;db.commit()
            item=comparison_history(first['id'],db,admin)[0]
            assert item['status']=='corrupt' and item['result'] is None
        event.details=intact;db.commit()
        tampered=deepcopy(event.details);tampered['comparison']['periods'][0]['draft']='wrong'
        event.details=tampered
        db.add(AuditEvent(actor_id=admin.id,action='metric_draft_synthetic_compared',object_id=first['id'],
                          details={'digest':first['digest'],'target':'gmv_from_factors'}));db.commit()
        assert {item['status'] for item in comparison_history(first['id'],db,admin)}=={'corrupt','unavailable'}
        assert all(item['result'] is None for item in comparison_history(first['id'],db,admin))
        with pytest.raises(HTTPException) as denied:
            compare_draft_synthetic(first['id'],SyntheticComparisonInput(target='gmv_from_factors'),db,analyst)
        assert denied.value.status_code==403
        with pytest.raises(HTTPException) as denied:
            comparison_history(first['id'],db,analyst)
        assert denied.value.status_code==403
        for values in ({**inputs,'visits':'0'}, {**inputs,'not_a_metric':'1'}, {**inputs,'tax_cost':'NaN'}):
            with pytest.raises(HTTPException) as invalid:
                preview_draft(first['id'],MetricPreviewInput(target='gmv_from_factors',inputs=values),db,admin)
            assert invalid.value.status_code==422
        with pytest.raises(HTTPException) as denied:
            preview_draft(first['id'],MetricPreviewInput(target='gmv_from_factors',inputs=inputs),db,analyst)
        assert denied.value.status_code==403
        with pytest.raises(HTTPException) as denied:
            create_draft(MetricDraftInput(scenario='ecommerce',name='越权',definitions=original),db,analyst)
        assert denied.value.status_code==403
        for operation in (lambda:template('ecommerce',analyst),lambda:list_drafts(db,analyst,'ecommerce'),
                          lambda:get_draft(first['id'],db,analyst)):
            with pytest.raises(HTTPException) as denied:
                operation()
            assert denied.value.status_code==403
        invalid=deepcopy(original); invalid['visits']['expression']={'ref':'visits'}
        with pytest.raises(HTTPException) as cycle:
            create_draft(MetricDraftInput(scenario='ecommerce',name='循环',definitions=invalid),db,admin)
        assert cycle.value.status_code==422
        assert '指标依赖存在循环' in cycle.value.detail
        invalid=deepcopy(original); invalid['gmv_from_factors']['expression']=None
        with pytest.raises(HTTPException) as root:
            create_draft(MetricDraftInput(scenario='ecommerce',name='无根公式',definitions=invalid),db,admin)
        assert root.value.status_code==422
        assert len(list_drafts(db,admin,'ecommerce'))==2
        db.get(MetricDraft,first['id']).definitions={'tampered':True};db.commit()
        with pytest.raises(HTTPException) as corrupt:
            get_draft(first['id'],db,admin)
        assert corrupt.value.status_code==409
        assert get_draft(second['id'],db,admin)['definitions']==original
    engine.dispose()


def test_http_routes_authorize_and_leave_builtin_catalog_unchanged(tmp_path):
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker
    from app.access import identity
    from app.config import settings
    from app.db import database
    from app.main import app
    engine=create_engine(f"sqlite:///{tmp_path / 'drafts.sqlite'}",connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine,tables=[User.__table__,MetricDraft.__table__,AuditEvent.__table__])
    factory=sessionmaker(engine,expire_on_commit=False)
    with factory.begin() as db:
        db.add_all([User(id='admin',username='admin',password_hash='unused',role='admin',domains=[],active=True),
                    User(id='analyst',username='analyst',password_hash='unused',role='analyst',domains=['ecommerce'],active=True)])
    identity_id=['admin']
    def fake_identity():
        with factory() as db: return db.get(User,identity_id[0])
    def fake_db():
        with factory() as db: yield db
    app.dependency_overrides[identity]=fake_identity
    app.dependency_overrides[database]=fake_db
    try:
        with TestClient(app,base_url=settings().public_origin) as client:
            client.headers['origin']=settings().public_origin
            result=client.get('/api/v1/admin/metric-drafts/template/ecommerce')
            assert result.status_code==200
            payload={'scenario':'ecommerce','name':'HTTP 草稿','definitions':result.json()['definitions']}
            created=client.post('/api/v1/admin/metric-drafts',json=payload)
            assert created.status_code==201 and created.json()['status']=='draft'
            assert len(client.get('/api/v1/admin/metric-drafts?scenario=ecommerce').json())==1
            preview_url='/api/v1/admin/metric-drafts/'+created.json()['id']+'/preview'
            preview_payload={'target':'gmv_from_factors',
                             'inputs':{'visits':'100000','orders':'5000','sales_amount':'1000000'}}
            preview=client.post(preview_url,json=preview_payload)
            assert preview.status_code==200 and preview.json()['value']=='1000000.00'
            assert client.post(preview_url,json={**preview_payload,'inputs':{'visits':'0','orders':'0','sales_amount':'0'}}).status_code==422
            compare_url='/api/v1/admin/metric-drafts/'+created.json()['id']+'/compare-synthetic'
            comparison=client.post(compare_url,json={'target':'gmv_from_factors'})
            assert comparison.status_code==200 and len(comparison.json()['periods'])==2
            history_url='/api/v1/admin/metric-drafts/'+created.json()['id']+'/comparisons'
            history=client.get(history_url)
            assert history.status_code==200 and history.json()[0]['status']=='available'
            assert history.json()[0]['result']['periods']==comparison.json()['periods']
            assert client.post(compare_url,json={'target':'sample_net_profit'}).status_code==422
            identity_id[0]='analyst'
            assert client.get('/api/v1/admin/metric-drafts?scenario=ecommerce').status_code==403
            assert client.post('/api/v1/admin/metric-drafts',json=payload).status_code==403
            assert client.post(preview_url,json=preview_payload).status_code==403
            assert client.post(compare_url,json={'target':'gmv_from_factors'}).status_code==403
            assert client.get(history_url).status_code==403
            assert client.get('/api/v1/metrics/ecommerce').json()['version']==catalog('ecommerce')['version']
    finally:
        app.dependency_overrides.pop(identity,None)
        app.dependency_overrides.pop(database,None)
        engine.dispose()
