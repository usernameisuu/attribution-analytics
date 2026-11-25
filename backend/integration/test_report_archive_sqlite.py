"""ORM persistence and ownership using an ephemeral in-memory SQLite database.

This does not test PostgreSQL migrations or row locking semantics.
"""
import os
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

with patch.dict(os.environ, {'ATTRIBUTION_DATABASE_URL':'postgresql+psycopg://unused:unused@127.0.0.1/unused'}):
    from app.db import AnalysisSession, AuditEvent, Base, ReportArchive, ReportPublication, User
    from app.domain.scenarios import calculate
    from app.modules.analysis.archive_api import (ArchiveInput, create_archive, export_archive, list_archives,
        publish_report, withdraw_report, list_published_reports, preview_published_report, export_published_report)
    from app.modules.analysis.snapshot import report_revision


def test_archive_is_persisted_and_owner_scoped_across_transactions():
    engine=create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine,tables=[User.__table__, AnalysisSession.__table__, ReportArchive.__table__, ReportPublication.__table__, AuditEvent.__table__])
    with Session(engine,expire_on_commit=False) as db:
        analyst=User(id='analyst',username='analyst',password_hash='unused',role='analyst',domains=['ecommerce'],active=True)
        other=User(id='other',username='other',password_hash='unused',role='analyst',domains=['ecommerce'],active=True)
        snapshot=calculate('ecommerce')
        snapshot['report_note']={'text':'归档时的说明','author':'analyst','updated_at':'2026-11-25T00:00:00+00:00'}
        session=AnalysisSession(id='session-1',owner_id=analyst.id,scenario='ecommerce',title='电商',snapshot=snapshot)
        db.add_all([analyst,other,session]);db.commit()
        event_snapshot={'status':'available','events':[], 'checked_at':'2026-11-24T00:00:00+00:00',
                        'current_window':['2026-10-01','2026-10-02'],'filters':{},'truncated':False,'notice':'时间重合不证明因果。'}
        with patch('app.modules.analysis.archive_api.report_view',return_value=event_snapshot):
            created=create_archive(session.id,ArchiveInput(revision=report_revision(session.snapshot)),db,analyst)
        session.snapshot={**session.snapshot,'title':'更新后的标题',
                          'report_note':{'text':'更新后的说明','author':'analyst','updated_at':'2026-11-25T01:00:00+00:00'}};db.commit()
        assert len(list_archives(session.id,db,analyst))==1
        assert list_published_reports(db,other)==[]
        with pytest.raises(HTTPException) as denied:
            preview_published_report(created['id'],db,other)
        assert denied.value.status_code==404
        assert publish_report(created['id'],db,analyst)['published']
        assert list_archives(session.id,db,analyst)[0]['published']
        assert len(list_published_reports(db,other))==1
        assert '归档时的说明' in preview_published_report(created['id'],db,other)['markdown']
        assert '归档时的说明' in export_published_report(created['id'],'md',db,other).body.decode('utf-8')
        other.domains=[];db.commit()
        assert list_published_reports(db,other)==[]
        with pytest.raises(HTTPException) as denied:
            preview_published_report(created['id'],db,other)
        assert denied.value.status_code==404
        other.domains=['ecommerce'];db.commit()
        with pytest.raises(HTTPException) as denied:
            withdraw_report(created['id'],db,other)
        assert denied.value.status_code==404
        assert not withdraw_report(created['id'],db,analyst)['published']
        with pytest.raises(HTTPException) as denied:
            export_published_report(created['id'],'md',db,other)
        assert denied.value.status_code==404
        assert publish_report(created['id'],db,analyst)['published']
        archived_snapshot=db.get(ReportArchive,created['id']).snapshot
        db.get(ReportArchive,created['id']).snapshot={'tampered':True};db.commit()
        with pytest.raises(HTTPException) as damaged:
            preview_published_report(created['id'],db,other)
        assert damaged.value.status_code==409
        db.get(ReportArchive,created['id']).snapshot=archived_snapshot;db.commit()
        rendered=export_archive(created['id'],'md',db,analyst).body.decode('utf-8')
        assert '电商 GMV 下滑' in rendered and '更新后的标题' not in rendered
        assert '归档时的说明' in rendered and '更新后的说明' not in rendered
        assert '当前公式局部敏感性' in rendered and '不是历史估计' in rendered
        with pytest.raises(HTTPException) as failure:
            export_archive(created['id'],'md',db,other)
        assert failure.value.status_code==404
        analyst.domains=[];db.commit()
        with pytest.raises(HTTPException) as failure:
            export_archive(created['id'],'md',db,analyst)
        assert failure.value.status_code==403
    engine.dispose()


def test_publication_http_access_and_withdrawal(tmp_path):
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker
    from app.access import identity
    from app.config import settings
    from app.db import database
    from app.main import app
    engine=create_engine(f"sqlite:///{tmp_path / 'publication.sqlite'}",connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine)
    factory=sessionmaker(engine,expire_on_commit=False)
    with factory.begin() as db:
        db.add_all([User(id='owner',username='owner',password_hash='unused',role='analyst',domains=['ecommerce'],active=True),
                    User(id='viewer',username='viewer',password_hash='unused',role='manager',domains=['ecommerce'],active=True),
                    User(id='outsider',username='outsider',password_hash='unused',role='manager',domains=['consumer'],active=True)])
        snapshot=calculate('ecommerce')
        db.add(AnalysisSession(id='session',owner_id='owner',scenario='ecommerce',title='电商',snapshot=snapshot))
        db.add(ReportArchive(id='report',owner_id='owner',session_id='session',scenario='ecommerce',title='电商',snapshot=snapshot,digest=report_revision(snapshot)))
    current=['owner']
    def fake_identity():
        with factory() as db: return db.get(User,current[0])
    def fake_db():
        with factory() as db: yield db
    app.dependency_overrides[identity]=fake_identity
    app.dependency_overrides[database]=fake_db
    try:
        with TestClient(app,base_url=settings().public_origin) as client:
            client.headers['origin']=settings().public_origin
            assert client.put('/api/v1/reports/report/publication').status_code==200
            current[0]='viewer'
            assert len(client.get('/api/v1/published-reports').json())==1
            assert client.get('/api/v1/published-reports/report').status_code==200
            assert client.get('/api/v1/published-reports/report/export/md').status_code==200
            created=client.post('/api/v1/published-reports/report/comments',json={'body':'  <script>意见</script>  '})
            assert created.status_code==201 and created.json()['body']=='<script>意见</script>'
            comment=created.json()
            url='/api/v1/published-reports/report/comments/'+comment['id']
            assert client.put(url,json={'body':'修改','revision':1}).json()['revision']==2
            assert client.put(url,json={'body':'过期修改','revision':1}).status_code==409
            assert client.post('/api/v1/published-reports/report/comments',json={'body':'\u0000'}).status_code==422
            current[0]='owner'
            assert client.get('/api/v1/published-reports/report/comments').json()[0]['body']=='修改'
            assert client.put(url,json={'body':'越权','revision':2}).status_code==404
            current[0]='viewer'
            assert client.delete('/api/v1/reports/report/publication').status_code==404
            current[0]='outsider'
            assert client.get('/api/v1/published-reports').json()==[]
            assert client.get('/api/v1/published-reports/report').status_code==404
            assert client.get('/api/v1/published-reports/report/comments').status_code==404
            current[0]='owner'
            assert client.delete('/api/v1/reports/report/publication').status_code==200
            current[0]='viewer'
            assert client.get('/api/v1/published-reports/report').status_code==404
            assert client.post('/api/v1/published-reports/report/comments',json={'body':'撤回后'}).status_code==404
            assert client.put(url,json={'body':'撤回后','revision':2}).status_code==404
    finally:
        app.dependency_overrides.pop(identity,None)
        app.dependency_overrides.pop(database,None)
        engine.dispose()
