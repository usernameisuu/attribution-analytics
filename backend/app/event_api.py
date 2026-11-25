"""Private business-event entry and association with an owned analysis."""
from typing import Annotated, Literal
from datetime import date
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from .access import DB, Identity, authorize, owned
from .db import AuditEvent, BusinessEvent
from .domain.event_matching import match_events
from .modules.events.matching import event_revision, info, match_for_session

router = APIRouter(prefix='/api/v1')


class EventInput(BaseModel):
    scenario: Literal['ecommerce', 'consumer']
    title: str = Field(min_length=1, max_length=160)
    start: str = Field(min_length=10, max_length=10)
    end: str = Field(min_length=10, max_length=10)
    source: str = Field(min_length=1, max_length=200)
    scope: dict[str, list[str]] = Field(default_factory=dict)


class EventUpdate(EventInput):
    revision: str = Field(min_length=64, max_length=64, pattern=r'^[0-9a-f]{64}$')


@router.get('/business-events')
def list_business_events(scenario: Literal['ecommerce', 'consumer'], db: DB, user: Identity,
                         start: date | None = None, end: date | None = None,
                         after_start: date | None = None, after_id: str | None = None):
    authorize(user, scenario)
    if start and end and start > end:
        raise HTTPException(422, '筛选开始日期不能晚于结束日期')
    if (after_start is None) != (after_id is None) or (after_id is not None and not 1 <= len(after_id) <= 36):
        raise HTTPException(422, '分页游标无效')
    query = select(BusinessEvent).where(BusinessEvent.owner_id == user.id, BusinessEvent.scenario == scenario)
    if start:
        query = query.where(BusinessEvent.end >= start.isoformat())
    if end:
        query = query.where(BusinessEvent.start <= end.isoformat())
    if after_start is not None:
        cursor_date = after_start.isoformat()
        query = query.where(or_(BusinessEvent.start < cursor_date,
                                and_(BusinessEvent.start == cursor_date, BusinessEvent.id > after_id)))
    records = list(db.scalars(query.order_by(BusinessEvent.start.desc(), BusinessEvent.id).limit(101)))
    page = records[:100]
    next_cursor = {'start':page[-1].start, 'id':page[-1].id} if len(records) > 100 else None
    return {'events':[info(record) for record in page], 'truncated':bool(next_cursor), 'next_cursor':next_cursor}


def validated_event(payload):
    candidate = dict(id='validation', business_line=payload.scenario, title=payload.title.strip(),
                     start=payload.start, end=payload.end, scope=payload.scope, source=payload.source.strip())
    try:
        match_events([candidate], payload.scenario, payload.start, payload.end, {})
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return candidate


@router.post('/business-events', status_code=201)
def create_business_event(payload: EventInput, db: DB, user: Identity):
    authorize(user, payload.scenario, write=True)
    candidate = validated_event(payload)
    record = BusinessEvent(owner_id=user.id, scenario=payload.scenario, title=candidate['title'],
                           start=payload.start, end=payload.end, scope=payload.scope, source=candidate['source'])
    db.add(record)
    db.flush()
    db.add(AuditEvent(actor_id=user.id, action='business_event_created', object_id=record.id,
                      details={'scenario': record.scenario}))
    db.commit()
    return info(record)


def event_owned(db, user, event_id, lock=False):
    query = select(BusinessEvent).where(BusinessEvent.id == event_id, BusinessEvent.owner_id == user.id)
    record = db.scalar(query.with_for_update() if lock else query)
    if not record:
        raise HTTPException(404, '事件不存在或无权访问')
    authorize(user, record.scenario, write=True)
    return record


@router.put('/business-events/{event_id}')
def update_business_event(event_id: str, payload: EventUpdate, db: DB, user: Identity):
    record = event_owned(db, user, event_id, lock=True)
    if event_revision(record) != payload.revision:
        raise HTTPException(409, '事件已被更新，请保留当前输入并刷新后核对')
    if payload.scenario != record.scenario:
        raise HTTPException(422, '不能更改事件业务线')
    candidate = validated_event(payload)
    record.title, record.start, record.end = candidate['title'], candidate['start'], candidate['end']
    record.source, record.scope = candidate['source'], candidate['scope']
    db.add(AuditEvent(actor_id=user.id, action='business_event_updated', object_id=record.id,
                      details={'scenario': record.scenario}))
    db.commit()
    return info(record)


@router.delete('/business-events/{event_id}', status_code=204)
def delete_business_event(event_id: str, db: DB, user: Identity,
                          revision: Annotated[str, Query(min_length=64, max_length=64, pattern=r'^[0-9a-f]{64}$')]):
    record = event_owned(db, user, event_id, lock=True)
    if event_revision(record) != revision:
        raise HTTPException(409, '事件已被更新，请刷新后核对再删除')
    db.add(AuditEvent(actor_id=user.id, action='business_event_deleted', object_id=record.id,
                      details={'scenario': record.scenario, 'revision':revision}))
    db.delete(record)
    db.commit()


@router.get('/sessions/{session_id}/business-events')
def session_business_events(session_id: str, db: DB, user: Identity):
    session = owned(db, user, session_id)
    return match_for_session(db, user, session)
