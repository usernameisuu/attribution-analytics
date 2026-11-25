import os
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

with patch.dict(os.environ, {'ATTRIBUTION_DATABASE_URL':'postgresql+psycopg://unused@127.0.0.1/unused'}):
    from app import worker


class WorkerBriefingTests(unittest.TestCase):
    def test_idle_worker_polls_briefings(self):
        db=object()
        @contextmanager
        def transaction(): yield db
        with patch.object(worker.SessionFactory,'begin',side_effect=transaction), \
             patch.object(worker,'generate_due') as generate, patch.object(worker,'claim',return_value=None):
            self.assertFalse(worker.poll_once())
            generate.assert_called_once_with(db)

    def test_briefing_failure_does_not_prevent_analysis_claim(self):
        @contextmanager
        def transaction(): yield object()
        with patch.object(worker.SessionFactory,'begin',side_effect=transaction), \
             patch.object(worker,'generate_due',side_effect=RuntimeError('briefing failed')), \
             patch.object(worker,'claim',return_value=('run','fence')), \
             patch.object(worker,'process') as process, self.assertLogs(worker.log,level='ERROR'):
            self.assertTrue(worker.poll_once())
            process.assert_called_once_with('run','fence')

    def test_heartbeat_does_not_run_briefings(self):
        run=Mock()
        stop=Mock();stop.wait.side_effect=[False,True]
        @contextmanager
        def transaction(): yield object()
        with patch.object(worker.SessionFactory,'begin',side_effect=transaction), \
             patch.object(worker,'current',return_value=run), patch.object(worker,'generate_due') as generate:
            worker.heartbeat('run','fence',stop)
            generate.assert_not_called()
            self.assertIsNotNone(run.lease_until)
