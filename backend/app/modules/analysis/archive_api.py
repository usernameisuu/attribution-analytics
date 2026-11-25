"""Frozen report archives, publication and collaborative comments."""
from copy import deepcopy
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update

from ...access import DB, Identity, authorize, owned
from ...db import AuditEvent, ReportArchive, ReportPublication, ReportComment, User, utcnow
from ...domain.sensitivity import capture_formula_sensitivity
from ..events.matching import report_view
from .exporters import pdf, spreadsheet
from .report import markdown_report_text
from .report_evidence import capture_variability
from .snapshot import report_revision
from .publication_clock import lock_publication_clock, publication_now

router = APIRouter(prefix='/api/v1', tags=['report archives'])


class ArchiveInput(BaseModel):
    revision: str = Field(min_length=64, max_length=64, pattern=r'^[0-9a-f]{64}$')


class CommentInput(BaseModel):
    body: str = Field(min_length=1, max_length=2000)

    @field_validator('body')
    @classmethod
    def valid_body(cls, value):
        value = value.strip()
        if not value or any(ord(c) < 32 and c not in '\n\r\t' for c in value):
            raise ValueError('批注不能为空或包含控制字符')
        return value


class CommentUpdate(CommentInput):
    revision: int = Field(ge=1)


def metadata(record):
    return {'id':record.id, 'session_id':record.session_id, 'scenario':record.scenario,
            'title':record.title, 'created_at':record.created_at.isoformat(), 'digest':record.digest,
            'status':'archived_draft'}


def report_owned(db, user, report_id):
    record = db.scalar(select(ReportArchive).where(ReportArchive.id == report_id, ReportArchive.owner_id == user.id))
    if not record:
        raise HTTPException(404, '报告不存在或无权访问')
    authorize(user, record.scenario)
    if report_revision(record.snapshot) != record.digest:
        raise HTTPException(409, '报告快照校验失败')
    return record


@router.post('/sessions/{session_id}/reports', status_code=201)
def create_archive(session_id: str, payload: ArchiveInput, db: DB, user: Identity):
    session = owned(db, user, session_id, lock=True)
    authorize(user, session.scenario, write=True)
    if report_revision(session.snapshot) != payload.revision:
        raise HTTPException(409, '会话内容已更新，请刷新后重新归档')
    events = report_view(db, user, session)
    events['mode'] = 'archived'
    snapshot = deepcopy({**session.snapshot, 'report_events': events,
                         'report_sensitivity':capture_formula_sensitivity(session.snapshot),
                         'report_variability':capture_variability(db, user, session)})
    digest = report_revision(snapshot)
    record = ReportArchive(owner_id=user.id, session_id=session.id, scenario=session.scenario,
                           title=session.title, snapshot=snapshot, digest=digest)
    db.add(record)
    db.flush()
    db.add(AuditEvent(actor_id=user.id, action='report_archived', object_id=record.id,
                      details={'session_id':session.id, 'digest':digest, 'events_checked_at':events['checked_at'],
                               'event_count':len(events['events']), 'events_truncated':events['truncated']}))
    db.commit()
    return metadata(record)


@router.get('/sessions/{session_id}/reports')
def list_archives(session_id: str, db: DB, user: Identity):
    session = owned(db, user, session_id)
    records = db.scalars(select(ReportArchive).where(ReportArchive.owner_id==user.id,
                         ReportArchive.session_id==session.id).order_by(ReportArchive.created_at.desc()).limit(100))
    return [{**metadata(record), 'published':bool((publication := db.get(ReportPublication, record.id)) and publication.active)} for record in records]


@router.put('/reports/{report_id}/publication')
def publish_report(report_id: str, db: DB, user: Identity):
    lock_publication_clock(db)
    # Lock the archive even for a first publication, when no publication row exists.
    db.scalar(select(ReportArchive).where(ReportArchive.id==report_id, ReportArchive.owner_id==user.id).with_for_update())
    record = report_owned(db, user, report_id)
    authorize(user, record.scenario, write=True)
    publication = db.get(ReportPublication, report_id)
    if not publication:
        publication = ReportPublication(report_id=report_id, active=True, published_at=publication_now(db))
        db.add(publication)
    elif not publication.active:
        publication.active = True
        publication.published_at = publication_now(db)
    else:
        return {'published':True}
    db.add(AuditEvent(actor_id=user.id, action='report_published', object_id=report_id,
                      details={'digest':record.digest, 'scenario':record.scenario}))
    db.commit()
    return {'published':True}


@router.delete('/reports/{report_id}/publication')
def withdraw_report(report_id: str, db: DB, user: Identity):
    db.scalar(select(ReportArchive).where(ReportArchive.id==report_id, ReportArchive.owner_id==user.id).with_for_update())
    record = report_owned(db, user, report_id)
    authorize(user, record.scenario, write=True)
    publication = db.scalar(select(ReportPublication).where(ReportPublication.report_id==report_id).with_for_update())
    if publication and publication.active:
        publication.active = False
        db.add(AuditEvent(actor_id=user.id, action='report_withdrawn', object_id=report_id,
                          details={'digest':record.digest, 'scenario':record.scenario}))
        db.commit()
    return {'published':False}


@router.get('/published-reports')
def list_published_reports(db: DB, user: Identity):
    if not user.active:
        raise HTTPException(403, '账号已停用')
    rows = db.execute(select(ReportArchive, ReportPublication).join(ReportPublication)
        .where(ReportPublication.active.is_(True), ReportArchive.scenario.in_(user.domains))
        .order_by(ReportPublication.published_at.desc(), ReportArchive.id.desc()).limit(100))
    return [{**metadata(record), 'published_at':publication.published_at.isoformat()} for record, publication in rows]


def published_report(db, user, report_id):
    row = db.execute(select(ReportArchive, ReportPublication).join(ReportPublication)
        .where(ReportArchive.id==report_id, ReportPublication.active.is_(True),
               ReportArchive.scenario.in_(user.domains))
        .with_for_update(read=True, of=ReportPublication)).first()
    if not row:
        raise HTTPException(404, '报告不存在或无权访问')
    record, _ = row
    authorize(user, record.scenario)
    if report_revision(record.snapshot) != record.digest:
        raise HTTPException(409, '报告快照校验失败')
    return record


@router.get('/published-reports/{report_id}')
def preview_published_report(report_id: str, db: DB, user: Identity):
    record = published_report(db, user, report_id)
    snapshot = {**record.snapshot, 'archive_context': {'id':record.id, 'digest':record.digest,
                                                        'created_at':record.created_at.isoformat()}}
    return {**metadata(record), 'markdown':markdown_report_text(snapshot)}


def comment_data(comment, author, user):
    return {'id':comment.id, 'body':comment.body, 'author':author.username,
            'editable':comment.author_id == user.id, 'revision':comment.revision,
            'created_at':comment.created_at.isoformat(), 'updated_at':comment.updated_at.isoformat()}


@router.get('/published-reports/{report_id}/comments')
def list_comments(report_id: str, db: DB, user: Identity):
    published_report(db, user, report_id)
    rows = db.execute(select(ReportComment, User).join(User, User.id==ReportComment.author_id)
        .where(ReportComment.report_id==report_id)
        .order_by(ReportComment.created_at.desc(), ReportComment.id.desc()).limit(100))
    return [comment_data(comment, author, user) for comment, author in rows]


@router.post('/published-reports/{report_id}/comments', status_code=201)
def create_comment(report_id: str, payload: CommentInput, db: DB, user: Identity):
    report = published_report(db, user, report_id)
    comment = ReportComment(report_id=report_id, author_id=user.id, body=payload.body,
                            revision=1, created_at=utcnow(), updated_at=utcnow())
    db.add(comment)
    db.flush()
    db.add(AuditEvent(actor_id=user.id, action='report_comment_created', object_id=comment.id,
                      details={'report_id':report_id, 'report_digest':report.digest, 'revision':1}))
    db.commit()
    return comment_data(comment, user, user)


@router.put('/published-reports/{report_id}/comments/{comment_id}')
def update_comment(report_id: str, comment_id: str, payload: CommentUpdate, db: DB, user: Identity):
    report = published_report(db, user, report_id)
    comment = db.scalar(select(ReportComment).where(ReportComment.id==comment_id,
                        ReportComment.report_id==report_id, ReportComment.author_id==user.id))
    if not comment:
        raise HTTPException(404, '批注不存在或无权修改')
    result = db.execute(update(ReportComment).where(ReportComment.id==comment_id,
                        ReportComment.revision==payload.revision).values(body=payload.body,
                        revision=payload.revision+1, updated_at=utcnow()))
    if result.rowcount != 1:
        raise HTTPException(409, '批注已被修改，请刷新后重试')
    db.add(AuditEvent(actor_id=user.id, action='report_comment_updated', object_id=comment_id,
                      details={'report_id':report_id, 'report_digest':report.digest, 'revision':payload.revision+1}))
    db.commit()
    db.refresh(comment)
    return comment_data(comment, user, user)


@router.get('/reports/{report_id}/export/{format}')
def export_archive(report_id: str, format: Literal['md','pdf','xlsx'], db: DB, user: Identity):
    record = report_owned(db, user, report_id)
    return export_record(record, format, db, user)


@router.get('/published-reports/{report_id}/export/{format}')
def export_published_report(report_id: str, format: Literal['md','pdf','xlsx'], db: DB, user: Identity):
    return export_record(published_report(db, user, report_id), format, db, user)


def export_record(record, format, db, user):
    snapshot = {**record.snapshot, 'archive_context': {'id':record.id, 'digest':record.digest,
                                                        'created_at':record.created_at.isoformat()}}
    if format == 'md':
        content, media = markdown_report_text(snapshot).encode('utf-8'), 'text/markdown; charset=utf-8'
    elif format == 'pdf':
        try:
            content = pdf(snapshot)
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        media = 'application/pdf'
    else:
        content, media = spreadsheet(snapshot), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    db.add(AuditEvent(actor_id=user.id, action='archived_report_exported', object_id=record.id,
                      details={'format':format, 'digest':record.digest}))
    db.commit()
    return Response(content, media_type=media,
                    headers={'Content-Disposition':f'attachment; filename="report-{record.id}.{format}"'})
