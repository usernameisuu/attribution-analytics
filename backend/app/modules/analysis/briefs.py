"""Periodic in-app manifests of published reports, not new analyses."""
from datetime import timedelta
from sqlalchemy import select
from ...db import BriefIssue, BriefSubscription, ReportArchive, ReportPublication, User
from .publication_clock import lock_publication_clock, publication_now


def interval(frequency):
    return timedelta(days=1 if frequency == 'daily' else 7)


def generate_due(db, now=None):
    lock_publication_clock(db)
    now = now or publication_now(db)
    sub = db.scalar(select(BriefSubscription).where(BriefSubscription.active.is_(True),
                    BriefSubscription.next_due <= now).order_by(BriefSubscription.next_due)
                    .with_for_update(skip_locked=True).limit(1))
    if not sub:
        return False
    user = db.scalar(select(User).where(User.id==sub.user_id).with_for_update(read=True)
                     .execution_options(populate_existing=True))
    if not user or not user.active or sub.scenario not in user.domains:
        sub.active = False
        return True
    rows = db.scalars(select(ReportArchive.id).join(ReportPublication)
        .where(ReportArchive.scenario==sub.scenario, ReportPublication.active.is_(True),
               ReportPublication.published_at>=sub.last_cutoff, ReportPublication.published_at<=now)
        .order_by(ReportPublication.published_at.desc(), ReportArchive.id.desc()).limit(101)).all()
    db.add(BriefIssue(subscription_id=sub.id, period_start=sub.last_cutoff, period_end=now,
                      report_ids=rows[:100], truncated=len(rows)>100, created_at=now))
    # Collapse downtime into one clearly bounded issue; do not fabricate missed issues.
    sub.last_cutoff = now
    sub.next_due = now + interval(sub.frequency)
    return True
