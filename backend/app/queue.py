import hashlib
import json
import secrets
from datetime import timedelta
from sqlalchemy import select, or_, and_
from .db import AnalysisRun, AnalysisSession, RunEvent, User, DatasetVersion, utcnow

ACTIVE = ('queued','running')


def emit(db, run, stage, **details):
    run.sequence += 1
    run.stage = stage
    db.add(RunEvent(run_id=run.id,sequence=run.sequence,payload=dict(stage=stage,status=run.status,**details)))


def enqueue(db, user, session, dataset, question, request_key, mode):
    db.refresh(session,with_for_update=True)
    request_hash = hashlib.sha256(json.dumps([session.id,dataset.id,question,mode],ensure_ascii=False).encode()).hexdigest()
    previous = db.scalar(select(AnalysisRun).where(AnalysisRun.owner_id==user.id,AnalysisRun.request_key==request_key))
    if previous:
        if previous.request_hash != request_hash: raise ValueError('幂等键已用于不同请求')
        return previous
    if db.scalar(select(AnalysisRun.id).where(AnalysisRun.session_id==session.id,AnalysisRun.status.in_(ACTIVE))):
        raise ValueError('RUN_BUSY：该会话已有运行中的任务')
    if session.snapshot.get('dataset_version') != dataset.id:
        raise ValueError('数据版本已绑定会话；切换版本请创建新会话')
    run = AnalysisRun(owner_id=user.id,session_id=session.id,dataset_id=dataset.id,
                      question=question,request_key=request_key,request_hash=request_hash,mode=mode,
                      scope=session.snapshot['scope'],parents=session.snapshot.get('scope_parents',[]),sequence=0,status='queued')
    db.add(run); db.flush(); emit(db,run,'queued',message='任务已持久化')
    return run


def authorized(db, run):
    user, dataset = db.get(User,run.owner_id), db.get(DatasetVersion,run.dataset_id)
    return bool(user and user.active and user.role=='analyst' and dataset and dataset.owner_id==user.id and dataset.scenario in user.domains)


def claim(db):
    run = db.scalar(select(AnalysisRun).where(or_(AnalysisRun.status=='queued',and_(AnalysisRun.status=='running',AnalysisRun.lease_until < utcnow()))).order_by(AnalysisRun.created_at).with_for_update(skip_locked=True).limit(1))
    if not run: return None
    if run.attempts >= 3 or not authorized(db,run):
        run.status='failed'; run.error='重试次数已用尽或授权已撤销'
        emit(db,run,'failed',message=run.error)
        return None
    run.attempts += 1
    run.fence = secrets.token_hex(24)
    run.status='running'; run.lease_until=utcnow()+timedelta(seconds=60)
    emit(db,run,'planning',message='执行范围解析',attempt=run.attempts)
    return run.id,run.fence


def current(db, run_id, fence):
    run = db.scalar(select(AnalysisRun).where(AnalysisRun.id==run_id).with_for_update())
    if not run or run.status!='running' or run.fence!=fence or not run.lease_until or run.lease_until<=utcnow() or not authorized(db,run):
        return None
    return run
