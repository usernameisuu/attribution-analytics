import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

with patch.dict(os.environ, {'ATTRIBUTION_DATABASE_URL':'postgresql+psycopg://unused@127.0.0.1/unused'}):
    from app.modules.analysis.publication_clock import lock_publication_clock, publication_now


class PublicationClockTests(unittest.TestCase):
    def test_postgresql_uses_transaction_lock_and_database_clock(self):
        db=Mock();db.get_bind.return_value=SimpleNamespace(dialect=SimpleNamespace(name='postgresql'))
        lock_publication_clock(db)
        sql=str(db.execute.call_args.args[0])
        self.assertIn('pg_advisory_xact_lock',sql)
        publication_now(db)
        self.assertIn('clock_timestamp',str(db.scalar.call_args.args[0]))

    def test_sqlite_does_not_claim_postgres_lock_support(self):
        db=Mock();db.get_bind.return_value=SimpleNamespace(dialect=SimpleNamespace(name='sqlite'))
        lock_publication_clock(db)
        db.execute.assert_not_called()
