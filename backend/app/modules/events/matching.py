"""Match only the current user's authorized events against a session window."""
from datetime import date, timedelta
import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import select

from ...db import BusinessEvent, utcnow
from ...domain.event_matching import match_events


def event_revision(record):
    content = {'id':record.id, 'scenario':record.scenario, 'title':record.title,
               'start':record.start, 'end':record.end, 'scope':record.scope, 'source':record.source}
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def info(record, include_revision=True):
    result = dict(id=record.id, business_line=record.scenario, title=record.title,
                  start=record.start, end=record.end, scope=record.scope, source=record.source)
    if include_revision:
        result['revision'] = event_revision(record)
    return result


def match_for_session(db, user, session):
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
        result = match_events([info(record, include_revision=False) for record in records[:1000]], session.scenario,
                              *scope['current'], scope['filters'])
        revisions = {record.id:event_revision(record) for record in records[:1000]}
        result = [{**event, 'revision':revisions[event['id']]} for event in result]
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(422, '当前分析范围无法用于事件匹配') from exc
    truncated = len(records) > 1000
    notice = '仅匹配当前范围前后 3 日的个人事件；时间关联不证明因果。'
    if truncated:
        notice += '候选事件超过 1000 条，仅检查最新的 1000 条，结果可能不完整。'
    return {'events': result, 'notice': notice, 'truncated': truncated}


def report_view(db, user, session):
    """Capture live event matches for this draft export without mutating the session."""
    checked_at = utcnow().isoformat()
    if not session.snapshot.get('scope'):
        return {'status': 'unavailable', 'checked_at': checked_at, 'events': [], 'truncated': False,
                'notice': '固定汇总样例没有日期范围，无法匹配事件。'}
    result = match_for_session(db, user, session)
    return {**result, 'status': 'available', 'checked_at': checked_at,
            'current_window': list(session.snapshot['scope']['current']),
            'filters': dict(session.snapshot['scope']['filters'])}
