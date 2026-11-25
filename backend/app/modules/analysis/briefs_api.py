"""Authenticated in-app report briefing subscriptions."""
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from ...access import DB, Identity, authorize
from ...db import AuditEvent, BriefIssue, BriefSubscription, ReportArchive, ReportPublication
from .briefs import interval
from .publication_clock import lock_publication_clock, publication_now

router = APIRouter(prefix='/api/v1', tags=['briefings'])


class SubscriptionInput(BaseModel):
    frequency: Literal['daily', 'weekly']


def subscription_data(sub):
    return {'scenario':sub.scenario, 'frequency':sub.frequency, 'active':sub.active,
            'next_due':sub.next_due.isoformat(), 'last_cutoff':sub.last_cutoff.isoformat()}


@router.get('/brief-subscriptions')
def subscriptions(db: DB, user: Identity):
    rows=db.scalars(select(BriefSubscription).where(BriefSubscription.user_id==user.id,
                    BriefSubscription.scenario.in_(user.domains)))
    return [subscription_data(row) for row in rows]


@router.put('/brief-subscriptions/{scenario}')
def subscribe(scenario: str, payload: SubscriptionInput, db: DB, user: Identity):
    authorize(user, scenario)
    lock_publication_clock(db)
    sub=db.scalar(select(BriefSubscription).where(BriefSubscription.user_id==user.id,
                  BriefSubscription.scenario==scenario).with_for_update())
    now=publication_now(db)
    if not sub:
        sub=BriefSubscription(user_id=user.id,scenario=scenario,frequency=payload.frequency,
                              active=True,last_cutoff=now,next_due=now+interval(payload.frequency))
        db.add(sub)
    elif not sub.active or sub.frequency!=payload.frequency:
        sub.active=True;sub.frequency=payload.frequency;sub.last_cutoff=now;sub.next_due=now+interval(payload.frequency)
    else:
        return subscription_data(sub)
    try:
        db.flush()
        db.add(AuditEvent(actor_id=user.id, action='brief_subscription_updated', object_id=sub.id,
                          details={'scenario':scenario,'frequency':payload.frequency,'active':True}))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409,'订阅已发生变化，请刷新后重试') from exc
    return subscription_data(sub)


@router.delete('/brief-subscriptions/{scenario}')
def unsubscribe(scenario: str, db: DB, user: Identity):
    authorize(user, scenario)
    sub=db.scalar(select(BriefSubscription).where(BriefSubscription.user_id==user.id,
                  BriefSubscription.scenario==scenario).with_for_update())
    if sub and sub.active:
        sub.active=False
        db.add(AuditEvent(actor_id=user.id,action='brief_subscription_updated',object_id=sub.id,
                          details={'scenario':scenario,'active':False}))
        db.commit()
    return {'active':False}


@router.get('/brief-issues/{scenario}')
def issues(scenario: str, db: DB, user: Identity):
    authorize(user, scenario)
    sub=db.scalar(select(BriefSubscription).where(BriefSubscription.user_id==user.id,
                  BriefSubscription.scenario==scenario))
    if not sub: return []
    records=db.scalars(select(BriefIssue).where(BriefIssue.subscription_id==sub.id)
                       .order_by(BriefIssue.created_at.desc(),BriefIssue.id.desc()).limit(50)).all()
    output=[]
    for issue in records:
        reports=db.execute(select(ReportArchive,ReportPublication).join(ReportPublication)
            .where(ReportArchive.id.in_(issue.report_ids),ReportArchive.scenario==scenario,
                   ReportPublication.active.is_(True),ReportPublication.published_at>=issue.period_start,
                   ReportPublication.published_at<=issue.period_end)
            .order_by(ReportPublication.published_at.desc(),ReportArchive.id.desc())).all()
        output.append({'id':issue.id,'period_start':issue.period_start.isoformat(),
                       'period_end':issue.period_end.isoformat(),'created_at':issue.created_at.isoformat(),
                       'truncated':issue.truncated,'unavailable_count':len(issue.report_ids)-len(reports),
                       'reports':[{'id':r.id,'title':r.title,'digest':r.digest} for r,_ in reports]})
    return output
