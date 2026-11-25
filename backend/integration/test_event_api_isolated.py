"""Exercise event API logic with a fake session; no database connection."""
import os
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

with patch.dict(os.environ, {'ATTRIBUTION_DATABASE_URL': os.environ.get('ATTRIBUTION_DATABASE_URL',
                'postgresql+psycopg://unused:unused@127.0.0.1/unused')}):
    from app.event_api import EventInput, EventUpdate, create_business_event, list_business_events, session_business_events, update_business_event, delete_business_event, router
    from app.modules.events.matching import event_revision
    from app.db import Base, BusinessEvent, User


class FakeDB:
    def __init__(self, records=()):
        self.records, self.added, self.committed, self.deleted = list(records), [], False, []

    def add(self, record):
        self.added.append(record)

    def flush(self):
        for record in self.added:
            if isinstance(record, BusinessEvent): record.id = 'new-event'

    def commit(self): self.committed = True
    def scalars(self, query): return iter(self.records)
    def scalar(self, query): return self.records[0] if self.records else None
    def delete(self, record): self.deleted.append(record)


class EventAPITests(unittest.TestCase):
    def setUp(self):
        self.user = SimpleNamespace(id='user', active=True, role='analyst', domains=['ecommerce'])
        self.payload = EventInput(scenario='ecommerce', title='  活动  ', start='2026-10-01',
                                  end='2026-10-02', source=' 日历 ', scope={'region':['华东']})

    def test_create_validates_authorization_and_records_audit(self):
        db = FakeDB()
        result = create_business_event(self.payload, db, self.user)
        self.assertEqual(result['title'], '活动')
        self.assertEqual(result['source'], '日历')
        self.assertTrue(db.committed)
        self.assertEqual(len(db.added), 2)
        self.user.role = 'manager'
        with self.assertRaises(HTTPException) as failure:
            create_business_event(self.payload, FakeDB(), self.user)
        self.assertEqual(failure.exception.status_code, 403)

    def test_create_route_is_unique_and_guarded(self):
        matches = [route for route in router.routes if route.path == '/api/v1/business-events' and 'POST' in route.methods]
        self.assertEqual(len(matches), 1)
        self.assertIs(matches[0].endpoint, create_business_event)

    def test_personal_event_list_filters_overlap_scenario_and_owner(self):
        engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(engine, tables=[User.__table__, BusinessEvent.__table__])
        with Session(engine) as db:
            db.add_all([User(id='user', username='user', password_hash='unused', role='analyst', domains=['ecommerce'], active=True),
                        User(id='other', username='other', password_hash='unused', role='analyst', domains=['ecommerce'], active=True)])
            for ident, owner, scenario, start, end in [('1','user','ecommerce','2026-10-01','2026-10-05'),
                                                       ('2','user','ecommerce','2026-10-20','2026-10-21'),
                                                       ('3','other','ecommerce','2026-10-03','2026-10-04'),
                                                       ('4','user','consumer','2026-10-03','2026-10-04')]:
                db.add(BusinessEvent(id=ident, owner_id=owner, scenario=scenario, title=ident,
                                     start=start, end=end, source='test', scope={}))
            db.commit()
            result = list_business_events('ecommerce', db, self.user, date(2026,10,5), date(2026,10,10))
            self.assertEqual([item['id'] for item in result['events']], ['1'])
            self.assertFalse(result['truncated'])
            with self.assertRaises(HTTPException) as failure:
                list_business_events('ecommerce', db, self.user, date(2026,10,11), date(2026,10,10))
            self.assertEqual(failure.exception.status_code, 422)
            with self.assertRaises(HTTPException) as failure:
                list_business_events('consumer', db, self.user)
            self.assertEqual(failure.exception.status_code, 403)
        engine.dispose()

    def test_event_pages_do_not_skip_events_sharing_a_start_date(self):
        engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(engine, tables=[User.__table__, BusinessEvent.__table__])
        with Session(engine) as db:
            db.add(User(id='user', username='user', password_hash='unused', role='analyst', domains=['ecommerce'], active=True))
            db.add_all([BusinessEvent(id=f'{i:03d}', owner_id='user', scenario='ecommerce', title=str(i),
                                     start='2026-10-01', end='2026-10-02', source='test', scope={}) for i in range(105)])
            db.commit()
            first = list_business_events('ecommerce', db, self.user)
            cursor = first['next_cursor']
            second = list_business_events('ecommerce', db, self.user, after_start=date.fromisoformat(cursor['start']), after_id=cursor['id'])
            ids = [item['id'] for item in first['events'] + second['events']]
            self.assertEqual(ids, [f'{i:03d}' for i in range(105)])
            self.assertIsNone(second['next_cursor'])
            with self.assertRaises(HTTPException) as failure:
                list_business_events('ecommerce', db, self.user, after_id='001')
            self.assertEqual(failure.exception.status_code, 422)
        engine.dispose()

    def test_rejects_invalid_event_and_matches_snapshot(self):
        self.payload.scope = {'bad': ['x']}
        with self.assertRaises(HTTPException) as failure:
            create_business_event(self.payload, FakeDB(), self.user)
        self.assertEqual(failure.exception.status_code, 422)
        record = SimpleNamespace(id='event', scenario='ecommerce', title='活动', start='2026-10-01',
                                 end='2026-10-01', scope={'region':['华东']}, source='日历')
        session = SimpleNamespace(scenario='ecommerce', snapshot={'scope': {'current':['2026-10-03','2026-10-04'],
                                     'filters':{'region':'华东'}}})
        with patch('app.event_api.owned', return_value=session):
            result = session_business_events('session', FakeDB([record]), self.user)
        self.assertEqual([item['id'] for item in result['events']], ['event'])
        self.assertFalse(result['truncated'])
        self.assertIn('不证明因果', result['notice'])

    def test_edit_delete_require_existing_authorized_event(self):
        record = SimpleNamespace(id='event', scenario='ecommerce', title='旧', start='2026-10-01',
                                 end='2026-10-01', scope={}, source='旧')
        db = FakeDB([record])
        update = EventUpdate(**self.payload.model_dump(), revision=event_revision(record))
        result = update_business_event('event', update, db, self.user)
        self.assertEqual(result['title'], '活动')
        self.assertTrue(db.committed)
        self.user.role = 'manager'
        with self.assertRaises(HTTPException) as failure:
            delete_business_event('event', db, self.user, event_revision(record))
        self.assertEqual(failure.exception.status_code, 403)
        self.user.role = 'analyst'
        with self.assertRaises(HTTPException) as failure:
            delete_business_event('unknown', FakeDB(), self.user, event_revision(record))
        self.assertEqual(failure.exception.status_code, 404)
        delete_business_event('event', db, self.user, event_revision(record))
        self.assertEqual(db.deleted, [record])

    def test_updated_event_scope_changes_matching_across_dimensions(self):
        record = SimpleNamespace(id='event', scenario='ecommerce', title='旧', start='2026-10-01',
                                 end='2026-10-01', scope={}, source='旧')
        self.payload.scope = {'channel':['自然流量','直播'], 'region':['华东'],
                              'category':['食品'], 'segment':['新客']}
        update = EventUpdate(**self.payload.model_dump(), revision=event_revision(record))
        update_business_event('event', update, FakeDB([record]), self.user)
        filters = {'channel':'直播', 'region':'华东', 'category':'食品', 'segment':'新客'}
        session = SimpleNamespace(scenario='ecommerce', snapshot={'scope':{'current':['2026-10-01','2026-10-02'],
                                                                           'filters':filters}})
        with patch('app.event_api.owned', return_value=session):
            self.assertEqual(len(session_business_events('s', FakeDB([record]), self.user)['events']), 1)
            filters['category'] = '服饰'
            self.assertEqual(session_business_events('s', FakeDB([record]), self.user)['events'], [])

    def test_stale_edit_is_rejected_without_overwriting_newer_event(self):
        record = SimpleNamespace(id='event', scenario='ecommerce', title='旧', start='2026-10-01',
                                 end='2026-10-01', scope={}, source='旧')
        stale_revision = event_revision(record)
        first = EventUpdate(**self.payload.model_dump(), revision=stale_revision)
        update_business_event('event', first, FakeDB([record]), self.user)
        stale = EventUpdate(**{**self.payload.model_dump(), 'title':'来自旧页面'}, revision=stale_revision)
        second_db = FakeDB([record])
        with self.assertRaises(HTTPException) as failure:
            update_business_event('event', stale, second_db, self.user)
        self.assertEqual(failure.exception.status_code, 409)
        self.assertEqual(record.title, '活动')
        self.assertFalse(second_db.committed)
        self.assertEqual(second_db.added, [])

    def test_stale_delete_does_not_remove_updated_event(self):
        record = SimpleNamespace(id='event', scenario='ecommerce', title='旧', start='2026-10-01',
                                 end='2026-10-01', scope={}, source='旧')
        old_revision = event_revision(record)
        record.title = '其他人已更新'
        db = FakeDB([record])
        with self.assertRaises(HTTPException) as failure:
            delete_business_event('event', db, self.user, old_revision)
        self.assertEqual(failure.exception.status_code, 409)
        self.assertFalse(db.committed)
        self.assertEqual(db.deleted, [])
        self.assertEqual(db.added, [])
        delete_business_event('event', db, self.user, event_revision(record))
        self.assertEqual(db.deleted, [record])
        self.assertTrue(db.committed)

    def test_report_event_matching_discloses_truncation_and_leaves_snapshot_untouched(self):
        from app.modules.events.matching import report_view
        record = SimpleNamespace(id='event', scenario='ecommerce', title='活动', start='2026-10-01',
                                 end='2026-10-01', scope={}, source='日历')
        session = SimpleNamespace(scenario='ecommerce', snapshot={'scope': {'current':['2026-10-03','2026-10-04'],
                                     'filters':{}}})
        result=report_view(FakeDB([record]*1001),self.user,session)
        self.assertTrue(result['truncated'])
        self.assertEqual(len(result['events']),1000)
        self.assertIn('结果可能不完整',result['notice'])
        self.assertIn('不证明因果',result['notice'])
        self.assertNotIn('report_events',session.snapshot)
