"""Private business-event entry and association with an owned analysis."""
from typing import Literal
from datetime import date, timedelta
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from .access import DB, Identity, authorize, owned
from .db import AuditEvent, BusinessEvent
from .domain.event_matching import match_events

router = APIRouter(prefix='/api/v1')


class EventInput(BaseModel):
    scenario: Literal['ecommerce', 'consumer']
    title: str = Field(min_length=1, max_length=160)
    start: str = Field(min_length=10, max_length=10)
    end: str = Field(min_length=10, max_length=10)
    source: str = Field(min_length=1, max_length=200)
    scope: dict[str, list[str]] = Field(default_factory=dict)


def info(record):
    return dict(id=record.id, business_line=record.scenario, title=record.title,
                start=record.start, end=record.end, scope=record.scope, source=record.source)


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


def event_owned(db, user, event_id):
    record = db.scalar(select(BusinessEvent).where(BusinessEvent.id == event_id,
                       BusinessEvent.owner_id == user.id))
    if not record:
        raise HTTPException(404, '事件不存在或无权访问')
    authorize(user, record.scenario, write=True)
    return record


@router.put('/business-events/{event_id}')
def update_business_event(event_id: str, payload: EventInput, db: DB, user: Identity):
    record = event_owned(db, user, event_id)
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
def delete_business_event(event_id: str, db: DB, user: Identity):
    record = event_owned(db, user, event_id)
    db.add(AuditEvent(actor_id=user.id, action='business_event_deleted', object_id=record.id,
                      details={'scenario': record.scenario}))
    db.delete(record)
    db.commit()


@router.get('/sessions/{session_id}/business-events')
def session_business_events(session_id: str, db: DB, user: Identity):
    session = owned(db, user, session_id)
    scope = session.snapshot.get('scope')
    if not scope:
        raise HTTPException(422, '固定汇总样例没有日期范围，无法匹配事件')
    try:
        start, end = (date.fromisoformat(value) for value in scope['current'])
        lower = (start - timedelta(days=min(3, (start-date.min).days))).isoformat()
        upper = (end + timedelta(days=min(3, (date.max-end).days))).isoformat()
        records = list(db.scalars(select(BusinessEvent).where(BusinessEvent.owner_id == user.id,
                       BusinessEvent.scenario == session.scenario, BusinessEvent.start <= upper,
                       BusinessEvent.end >= lower).order_by(BusinessEvent.created_at.desc(), BusinessEvent.id).limit(1001)))
        result = match_events([info(record) for record in records[:1000]], session.scenario,
                              *scope['current'], scope['filters'])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(422, '当前分析范围无法用于事件匹配') from exc
    truncated = len(records) > 1000
    notice = '仅匹配当前范围前后 3 日的个人事件；时间关联不证明因果。'
    if truncated:
        notice += '候选事件超过 1000 条，仅检查最新的 1000 条，结果可能不完整。'
    return {'events': result, 'notice': notice, 'truncated': truncated}
