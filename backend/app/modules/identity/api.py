"""HTTP endpoints for authentication and the current identity."""
from datetime import timedelta
import secrets

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ...access import COOKIE, DB, Identity
from ...config import settings
from ...db import AuditEvent, LoginSession, User, utcnow
from ...security import password_hash, password_matches, token_hash


router = APIRouter(prefix="/api/v1", tags=["identity"])
_DUMMY_PASSWORD = password_hash(secrets.token_urlsafe(32))


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


@router.post("/auth/login")
def login(payload: Credentials, response: Response, db: DB):
    attempts = db.scalar(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == "login_attempt",
            AuditEvent.object_id == payload.username,
            AuditEvent.created_at > utcnow() - timedelta(minutes=15),
        )
    )
    if attempts >= 10:
        raise HTTPException(429, "登录尝试过多，请 15 分钟后再试")
    user = db.scalar(select(User).where(User.username == payload.username))
    valid = password_matches(payload.password, user.password_hash if user else _DUMMY_PASSWORD)
    db.add(AuditEvent(
        actor_id=user.id if user else None,
        action="login_attempt",
        object_id=payload.username,
        details={"success": bool(user and user.active and valid)},
    ))
    if not user or not user.active or not valid:
        db.commit()
        raise HTTPException(401, "用户名或密码错误")
    raw, csrf = secrets.token_urlsafe(32), secrets.token_hex(32)
    config = settings()
    db.add(LoginSession(
        token_hash=token_hash(raw), user_id=user.id, csrf=csrf,
        expires_at=utcnow() + timedelta(hours=config.session_hours),
    ))
    db.commit()
    response.set_cookie(
        COOKIE, raw, httponly=True, secure=config.secure_cookie, samesite="strict",
        max_age=config.session_hours * 3600, path="/",
    )
    return {"username": user.username, "role": user.role, "domains": user.domains, "csrf": csrf}


@router.get("/me")
def me(request: Request, user: Identity):
    return {"username": user.username, "role": user.role, "domains": user.domains, "csrf": request.state.login.csrf}


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: DB, user: Identity):
    db.delete(request.state.login)
    db.commit()
    response.delete_cookie(COOKIE, path="/")
