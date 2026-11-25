"""Private dataset versions and replayable analysis tasks."""
import asyncio
import json
import time
from copy import deepcopy
from typing import Literal
from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .access import DB, Identity, authorize, owned, identity, administrator
from .db import DatasetVersion, AnalysisSession, AnalysisRun, RunEvent, AuditEvent, SessionFactory, BudgetAccount
from .domain.datasets import parse_upload, generate, normalize, DIMENSIONS
from .queue import enqueue, emit, ACTIVE
from .modules.datasets.access import dataset_owned
from .modules.analysis.report import markdown_report_text
from .modules.analysis.snapshot import serialize_session

router = APIRouter(prefix='/api/v1')


def dataset_info(record):
    days = sorted({r['date'] for r in record.rows})
    return dict(id=record.id, scenario=record.scenario, name=record.name, source_kind=record.source_kind, digest=record.digest,
                row_count=len(record.rows), start=days[0], end=days[-1],
                dimensions={k:sorted({r[k] for r in record.rows}) for k in DIMENSIONS})


class DatasetInput(BaseModel):
    scenario: Literal['ecommerce','consumer']
    name: str = Field(min_length=1, max_length=120)
    format: Literal['csv','json']
    content: str = Field(min_length=1, max_length=10_000_000)


class DemoInput(BaseModel):
    scenario: Literal['ecommerce','consumer']


def save_dataset(db, user, scenario, name, rows, digest, source_kind='imported'):
    previous = db.scalar(select(DatasetVersion).where(DatasetVersion.owner_id==user.id,
                         DatasetVersion.scenario==scenario, DatasetVersion.digest==digest))
    if previous:
        return dataset_info(previous)
    record = DatasetVersion(owner_id=user.id, scenario=scenario, name=name.strip(), source_kind=source_kind,rows=rows,digest=digest)
    db.add(record)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        previous=db.scalar(select(DatasetVersion).where(DatasetVersion.owner_id==user.id,
                               DatasetVersion.scenario==scenario,DatasetVersion.digest==digest))
        if previous: return dataset_info(previous)
        raise
    db.add(AuditEvent(actor_id=user.id, action='dataset_imported', object_id=record.id,
                      details={'digest':digest, 'rows':len(rows), 'scenario':scenario}))
    db.commit()
    return dataset_info(record)


@router.get('/datasets')
def datasets(db: DB, user: Identity):
    records = db.scalars(select(DatasetVersion).where(DatasetVersion.owner_id==user.id,
                          DatasetVersion.scenario.in_(user.domains)).order_by(DatasetVersion.created_at.desc()).limit(100))
    return [dataset_info(r) for r in records]


@router.post('/datasets', status_code=201)
def import_dataset(payload: DatasetInput, db: DB, user: Identity):
    authorize(user,payload.scenario,write=True)
    try:
        if not payload.name.strip(): raise ValueError('数据名称不能为空')
        rows, digest = parse_upload(payload.content,payload.format)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return save_dataset(db,user,payload.scenario,payload.name,rows,digest)


@router.post('/datasets/demo', status_code=201)
def demo_dataset(payload: DemoInput, db: DB, user: Identity):
    authorize(user,payload.scenario,write=True)
    rows, digest = normalize(generate(payload.scenario))
    return save_dataset(db,user,payload.scenario,'90 天合成日聚合样例（非真实业务）',rows,digest,'synthetic')


class RunInput(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    request_key: str = Field(min_length=8, max_length=80)
    mode: Literal['rules','deepseek'] = 'rules'


def run_owned(db, user, run_id, lock=False):
    query = select(AnalysisRun).where(AnalysisRun.id==run_id, AnalysisRun.owner_id==user.id)
    run = db.scalar(query.with_for_update() if lock else query)
    if not run: raise HTTPException(404, '任务不存在或无权访问')
    owned(db,user,run.session_id)
    dataset_owned(db,user,run.dataset_id)
    return run


def run_info(run):
    return dict(id=run.id, session_id=run.session_id, question=run.question, mode=run.mode,
                status=run.status, stage=run.stage, sequence=run.sequence, attempts=run.attempts,
                error=run.error, created_at=run.created_at.isoformat(),
                has_previous_drafts=bool(run.result and run.result.get('previous_snapshot')))


@router.post('/sessions/{session_id}/runs', status_code=202)
def create_run(session_id: str, payload: RunInput, db: DB, user: Identity):
    session = owned(db,user,session_id)
    authorize(user,session.scenario,write=True)
    dataset = dataset_owned(db,user,session.snapshot.get('dataset_version'))
    try:
        if not payload.question.strip(): raise ValueError('问题不能为空')
        run = enqueue(db,user,session,dataset,payload.question.strip(),payload.request_key,payload.mode)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(409,str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409,'存在并发请求，请使用同一幂等键重试') from exc
    return run_info(run)


@router.get('/sessions/{session_id}/runs')
def runs(session_id: str, db: DB, user: Identity):
    owned(db,user,session_id)
    return [run_info(r) for r in db.scalars(select(AnalysisRun).where(AnalysisRun.session_id==session_id,
                AnalysisRun.owner_id==user.id).order_by(AnalysisRun.created_at.desc()).limit(100))]


@router.get('/runs/{run_id}')
def get_run(run_id: str, db: DB, user: Identity):
    run = run_owned(db,user,run_id)
    return {**run_info(run), 'result':run.result}


@router.get('/runs/{run_id}/previous-draft.md')
def previous_draft_report(run_id: str, db: DB, user: Identity):
    run = run_owned(db, user, run_id)
    snapshot = (run.result or {}).get('previous_snapshot')
    if not snapshot:
        raise HTTPException(404, '该任务没有保留先前草稿')
    content = ('> 追问前的已保存草稿快照；未重新匹配业务事件。\n\n' + markdown_report_text(snapshot))
    db.add(AuditEvent(actor_id=user.id, action='previous_draft_exported', object_id=run.id,
                      details={'session_id':run.session_id, 'format':'markdown'}))
    db.commit()
    return PlainTextResponse(content, headers={'Content-Disposition':f'attachment; filename="previous-draft-{run.id}.md"'})


@router.post('/runs/{run_id}/restore-previous-draft', status_code=201)
def restore_previous_draft(run_id: str, db: DB, user: Identity):
    run = run_owned(db, user, run_id)
    dataset = dataset_owned(db, user, run.dataset_id)
    authorize(user, dataset.scenario, write=True)
    snapshot = (run.result or {}).get('previous_snapshot')
    if not snapshot:
        raise HTTPException(404, '该任务没有保留先前草稿')
    if (snapshot.get('scenario_id') != dataset.scenario or snapshot.get('dataset_version') != dataset.id
            or snapshot.get('data_digest') != dataset.digest):
        raise HTTPException(409, '草稿对应的数据版本不一致，无法恢复')
    record = AnalysisSession(owner_id=user.id, scenario=dataset.scenario,
                             title=snapshot['title'], snapshot=deepcopy(snapshot))
    db.add(record)
    db.flush()
    db.add(AuditEvent(actor_id=user.id, action='previous_draft_restored', object_id=record.id,
                      details={'source_run_id':run.id, 'source_session_id':run.session_id,
                               'dataset_version':dataset.id, 'data_digest':dataset.digest}))
    db.commit()
    return serialize_session(record)


@router.post('/runs/{run_id}/cancel')
def cancel_run(run_id: str, db: DB, user: Identity):
    run = run_owned(db,user,run_id,lock=True)
    authorize(user,db.get(DatasetVersion,run.dataset_id).scenario,write=True)
    if run.status in ACTIVE:
        run.status, run.fence, run.lease_until = 'cancelled', None, None
        emit(db,run,'cancelled',message='任务已取消；已发起的模型请求仍按实际用量结算')
        db.add(AuditEvent(actor_id=user.id,action='run_cancelled',object_id=run.id))
    db.commit()
    return run_info(run)


@router.get('/runs/{run_id}/events')
def run_events(run_id: str, request: Request, db: DB, user: Identity, after: int = Query(default=0,ge=0)):
    run_owned(db,user,run_id)
    try:
        cursor = max(after,int(request.headers.get('last-event-id','0')))
        if cursor < 0: raise ValueError()
    except ValueError as exc:
        raise HTTPException(422,'事件游标无效') from exc
    # FastAPI yield-dependency cleanup can run after streaming completes.
    # Release the initial authentication transaction before the first yield.
    db.close()

    def read_batch():
        with SessionFactory() as fresh:
            try:
                current_user = identity(request,fresh)
                run = run_owned(fresh,current_user,run_id)
            except HTTPException:
                return True,True,[]
            terminal = run.status not in ACTIVE
            batch = [(e.sequence,e.payload) for e in fresh.scalars(select(RunEvent).where(
                RunEvent.run_id==run_id,RunEvent.sequence>cursor).order_by(RunEvent.sequence).limit(100))]
            return False,terminal,batch

    async def stream():
        nonlocal cursor
        started, last_ping = time.monotonic(), 0.0
        while time.monotonic()-started < 110:
            if await request.is_disconnected(): return
            # Never retain a DB transaction across a yield. Recheck the cookie,
            # active account, ownership and business grants for every batch.
            denied,terminal,batch = await asyncio.to_thread(read_batch)
            if denied:
                yield 'event: access-revoked\ndata: {}\n\n'
                return
            for sequence,payload in batch:
                cursor = sequence
                yield f'id: {sequence}\nevent: progress\ndata: {json.dumps(payload,ensure_ascii=False)}\n\n'
            if terminal and len(batch)<100:
                yield 'event: done\ndata: {}\n\n'
                return
            if time.monotonic()-last_ping > 15:
                yield ': keepalive\n\n'
                last_ping = time.monotonic()
            await asyncio.sleep(1)
        # EventSource reconnects and supplies Last-Event-ID.
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'X-Accel-Buffering':'no'})


@router.get('/admin/budget')
def budget(db: DB, user: Identity):
    administrator(user)
    account = db.get(BudgetAccount,'development')
    return dict(limit=str(account.limit_cny), spent=str(account.spent_cny), reserved=str(account.reserved_cny),
                available=str(account.limit_cny-account.spent_cny-account.reserved_cny))
