"""Exercise briefing scheduling with isolated SQLite; not PostgreSQL lock validation."""
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

with patch.dict(os.environ, {'ATTRIBUTION_DATABASE_URL':'postgresql+psycopg://unused@127.0.0.1/unused'}):
    from app.db import Base, User, AnalysisSession, ReportArchive, ReportPublication, BriefIssue, BriefSubscription
    from app.modules.analysis.briefs import generate_due
    from app.modules.analysis.briefs_api import SubscriptionInput, subscribe, unsubscribe, issues


def test_schedule_issue_permissions_and_withdrawal():
    engine=create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    start=datetime(2026,1,1,tzinfo=timezone.utc)
    with Session(engine,expire_on_commit=False) as db:
        owner=User(id='owner',username='owner',password_hash='x',role='analyst',domains=['ecommerce'],active=True)
        viewer=User(id='viewer',username='viewer',password_hash='x',role='manager',domains=['ecommerce'],active=True)
        other=User(id='other',username='other',password_hash='x',role='manager',domains=['consumer'],active=True)
        db.add_all([owner,viewer,other]);db.flush()
        db.add(AnalysisSession(id='s',owner_id='owner',scenario='ecommerce',title='样例',snapshot={}))
        db.add(ReportArchive(id='r',owner_id='owner',session_id='s',scenario='ecommerce',title='报告',snapshot={},digest='x'*64))
        db.commit()
        with patch('app.modules.analysis.publication_clock.utcnow',return_value=start):
            subscribe('ecommerce',SubscriptionInput(frequency='daily'),db,viewer)
        # Include the exact boundary to avoid losing a commit sharing its timestamp.
        db.add(ReportPublication(report_id='r',active=True,published_at=start));db.commit()
        assert not generate_due(db,start+timedelta(hours=23))
        late=start+timedelta(days=3)
        assert generate_due(db,late);db.commit()
        assert not generate_due(db,late)
        first=issues('ecommerce',db,viewer)
        assert len(first)==1 and first[0]['reports'][0]['id']=='r'
        assert len(db.scalars(select(BriefIssue)).all())==1
        assert issues('ecommerce',db,owner)==[]
        with pytest.raises(HTTPException) as denied: issues('ecommerce',db,other)
        assert denied.value.status_code==403
        db.get(ReportPublication,'r').active=False;db.commit()
        assert issues('ecommerce',db,viewer)[0]['reports']==[]
        assert issues('ecommerce',db,viewer)[0]['unavailable_count']==1
        db.get(ReportPublication,'r').active=True
        db.get(ReportPublication,'r').published_at=late+timedelta(hours=1);db.commit()
        assert issues('ecommerce',db,viewer)[0]['reports']==[]
        assert generate_due(db,late+timedelta(days=1));db.commit()
        assert len(issues('ecommerce',db,viewer))==2
        unsubscribe('ecommerce',db,viewer)
        assert not generate_due(db,late+timedelta(days=2))
        with patch('app.modules.analysis.publication_clock.utcnow',return_value=late+timedelta(days=2)):
            subscribe('ecommerce',SubscriptionInput(frequency='weekly'),db,viewer)
        viewer.domains=[];db.commit()
        assert generate_due(db,late+timedelta(days=9));db.commit()
        assert not db.scalars(select(BriefSubscription).where(BriefSubscription.user_id=='viewer')).one().active
        with pytest.raises(HTTPException): issues('ecommerce',db,viewer)
    engine.dispose()


def test_briefing_http_is_user_and_domain_scoped(tmp_path):
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker
    from app.access import identity
    from app.config import settings
    from app.db import database
    from app.main import app
    engine=create_engine(f"sqlite:///{tmp_path / 'briefs.sqlite'}",connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine)
    factory=sessionmaker(engine,expire_on_commit=False)
    with factory.begin() as db:
        db.add_all([User(id='a',username='a',password_hash='x',role='manager',domains=['ecommerce'],active=True),
                    User(id='b',username='b',password_hash='x',role='manager',domains=['consumer'],active=True)])
    current=['a']
    def fake_identity():
        with factory() as db: return db.get(User,current[0])
    def fake_db():
        with factory() as db: yield db
    app.dependency_overrides[identity]=fake_identity;app.dependency_overrides[database]=fake_db
    try:
        with TestClient(app,base_url=settings().public_origin) as client:
            client.headers['origin']=settings().public_origin
            url='/api/v1/brief-subscriptions/ecommerce'
            assert client.put(url,json={'frequency':'daily'}).status_code==200
            assert client.put(url,json={'frequency':'hourly'}).status_code==422
            assert client.get('/api/v1/brief-subscriptions').json()[0]['active']
            assert client.get('/api/v1/brief-issues/ecommerce').json()==[]
            current[0]='b'
            assert client.get('/api/v1/brief-subscriptions').json()==[]
            assert client.get('/api/v1/brief-issues/ecommerce').status_code==403
            assert client.delete(url).status_code==403
            current[0]='a'
            assert client.delete(url).json()['active'] is False
    finally:
        app.dependency_overrides.pop(identity,None);app.dependency_overrides.pop(database,None)
        engine.dispose()
