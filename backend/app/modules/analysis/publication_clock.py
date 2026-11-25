"""Serialize publication timestamps and briefing cutoffs on PostgreSQL.

The lock is transaction scoped and held through commit. All writers of
ReportPublication must acquire it before assigning a publication time.
"""
from sqlalchemy import func, select
from ...db import utcnow


def lock_publication_clock(db):
    if db.get_bind().dialect.name == 'postgresql':
        db.execute(select(func.pg_advisory_xact_lock(721984, 411)))


def publication_now(db):
    if db.get_bind().dialect.name == 'postgresql':
        return db.scalar(select(func.clock_timestamp()))
    return utcnow()
