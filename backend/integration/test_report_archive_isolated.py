"""Exercise frozen report behavior without connecting to a database."""
import os
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from openpyxl import load_workbook

with patch.dict(os.environ, {'ATTRIBUTION_DATABASE_URL':'postgresql+psycopg://unused:unused@127.0.0.1/unused'}):
    from app.db import ReportArchive
    from app.domain.scenarios import calculate
    from app.modules.analysis.archive_api import ArchiveInput, create_archive, export_archive, report_owned
    from app.modules.analysis.snapshot import report_revision


class FakeDB:
    def __init__(self):
        self.added=[]
        self.commits=0
        self.report=None
        self.query=None
    def add(self, item): self.added.append(item)
    def flush(self):
        for item in self.added:
            if isinstance(item, ReportArchive):
                item.id='report-1'
                item.created_at=datetime(2026,11,24,tzinfo=timezone.utc)
                self.report=item
    def commit(self): self.commits+=1
    def scalar(self, query): self.query=query; return self.report


def user(role='analyst'):
    return SimpleNamespace(id='user-1',active=True,role=role,domains=['ecommerce'])


def test_archive_captures_a_copy_and_exports_frozen_event_data():
    session=SimpleNamespace(id='session-1',title='电商样例',scenario='ecommerce',snapshot=calculate('ecommerce'))
    events={'status':'available','events':[{'title':'活动','start':'2026-10-01','end':'2026-10-02',
            'scope':{},'source':'日历','evidence_status':'候选关联，尚不能证明因果'}],
            'checked_at':'2026-11-24T00:00:00+00:00','current_window':['2026-10-01','2026-10-02'],
            'filters':{},'truncated':False,'notice':'时间关联不证明因果。'}
    row={'key':'metric','label':'GMV','n':2,'missing_days':0,'mean':'100','stddev':'10','relative_percent':'10'}
    variability={'status':'available','notice':'不作为预测区间','window':['2026-09-01','2026-09-02'],
                 'filters':{},'days':2,'missing_dates':0,'dataset_version':'d1','data_digest':'digest',
                 'metric':row,'factors':[]}
    db=FakeDB()
    with patch('app.modules.analysis.archive_api.owned',return_value=session), patch('app.modules.analysis.archive_api.report_view',return_value=events), \
         patch('app.modules.analysis.archive_api.capture_variability',return_value=variability):
        created=create_archive('session-1',ArchiveInput(revision=report_revision(session.snapshot)),db,user())
    assert created['status']=='archived_draft'
    assert db.report.digest==report_revision(db.report.snapshot)
    session.snapshot['title']='变化后标题'
    events['events'][0]['title']='变化后事件'
    variability['metric']['mean']='999'
    assert db.report.snapshot['title'] != '变化后标题'
    assert db.report.snapshot['report_events']['events'][0]['title']=='活动'
    assert db.report.snapshot['report_variability']['metric']['mean']=='100'
    assert db.report.snapshot['report_events']['mode']=='archived'
    markdown=export_archive('report-1','md',db,user()).body.decode('utf-8')
    assert '活动' in markdown and '变化后事件' not in markdown
    assert '后续事件变更不影响此快照' in markdown and created['digest'] in markdown
    workbook=load_workbook(BytesIO(export_archive('report-1','xlsx',db,user()).body))
    assert workbook['事件关联']['B3'].value=='活动'
    assert workbook['基期每日波动']['D4'].value=='100'
    assert export_archive('report-1','pdf',db,user()).body.startswith(b'%PDF-')
    assert db.commits==4


def test_archive_checks_permissions_stale_content_and_digest():
    session=SimpleNamespace(id='session-1',title='样例',scenario='ecommerce',snapshot=calculate('ecommerce'))
    db=FakeDB()
    with patch('app.modules.analysis.archive_api.owned',return_value=session):
        with pytest.raises(HTTPException) as failure:
            create_archive('session-1',ArchiveInput(revision='0'*64),db,user())
        assert failure.value.status_code==409
        with pytest.raises(HTTPException) as failure:
            create_archive('session-1',ArchiveInput(revision=report_revision(session.snapshot)),db,user('manager'))
        assert failure.value.status_code==403
    assert not db.added and db.commits==0
    db.report=SimpleNamespace(scenario='ecommerce',snapshot={'value':1},digest='0'*64)
    with pytest.raises(HTTPException) as failure:
        report_owned(db,user(),'report-1')
    assert failure.value.status_code==409
    assert 'user-1' in db.query.compile().params.values()
