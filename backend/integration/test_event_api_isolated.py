"""Exercise event API logic with a fake session; no database connection."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

with patch.dict(os.environ, {'ATTRIBUTION_DATABASE_URL': os.environ.get('ATTRIBUTION_DATABASE_URL',
                'postgresql+psycopg://unused:unused@127.0.0.1/unused')}):
    from app.event_api import EventInput, create_business_event, session_business_events, update_business_event, delete_business_event, router
    from app.db import BusinessEvent


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
        result = update_business_event('event', self.payload, db, self.user)
        self.assertEqual(result['title'], '活动')
        self.assertTrue(db.committed)
        self.user.role = 'manager'
        with self.assertRaises(HTTPException) as failure:
            delete_business_event('event', db, self.user)
        self.assertEqual(failure.exception.status_code, 403)
        self.user.role = 'analyst'
        with self.assertRaises(HTTPException) as failure:
            delete_business_event('unknown', FakeDB(), self.user)
        self.assertEqual(failure.exception.status_code, 404)
        delete_business_event('event', db, self.user)
        self.assertEqual(db.deleted, [record])
