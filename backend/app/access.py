import hmac
from typing import Annotated
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from .db import database, User, LoginSession, AnalysisSession, utcnow
from .security import token_hash
from .domain.scenarios import SCENARIOS

DB = Annotated[Session, Depends(database)]
COOKIE = 'attribution_session'


def authorize(user: User, scenario: str, write: bool = False):
    if not user.active or scenario not in SCENARIOS or scenario not in user.domains:
        raise HTTPException(403, '无权访问该业务线')
    if write and user.role != 'analyst':
        raise HTTPException(403, '当前角色不能创建分析或模拟')


def identity(request: Request, db: DB) -> User:
    raw = request.cookies.get(COOKIE)
    login = db.get(LoginSession, token_hash(raw)) if raw else None
    if not login or login.expires_at <= utcnow():
        raise HTTPException(401, '请先登录')
    if request.method not in {'GET','HEAD'} and not hmac.compare_digest(request.headers.get('x-csrf-token',''),login.csrf):
        raise HTTPException(403, '请求校验失败，请刷新后重试')
    # Serialize permission and account updates with the authorization check
    # and the database transaction serving this request.
    user = db.scalar(select(User).where(User.id == login.user_id)
                     .with_for_update(read=True).execution_options(populate_existing=True))
    if not user or not user.active:
        raise HTTPException(401, '账号已停用')
    request.state.login = login
    return user


Identity = Annotated[User, Depends(identity)]


def owned(db: Session, user: User, session_id: str, lock: bool = False) -> AnalysisSession:
    query = select(AnalysisSession).where(AnalysisSession.id == session_id, AnalysisSession.owner_id == user.id)
    record = db.scalar(query.with_for_update() if lock else query)
    if not record: raise HTTPException(404, '会话不存在或无权访问')
    authorize(user,record.scenario)
    return record


def administrator(user: User):
    if user.role != 'admin': raise HTTPException(403, '需要系统管理员权限')
