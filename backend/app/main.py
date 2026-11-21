from datetime import timedelta
import secrets
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, func, text
from .config import settings
from .db import User, LoginSession, AnalysisSession, AuditEvent, utcnow
from .security import password_hash, password_matches, token_hash
from .domain.scenarios import SCENARIOS, calculate
from .domain.exploration import analyze, default_scope, simulate_snapshot
from .access import DB, Identity, COOKIE, authorize, owned
from .pipeline_api import router as pipeline_router, dataset_owned

app = FastAPI(title="经营归因分析系统", version="0.2.0")
app.include_router(pipeline_router)
DUMMY_PASSWORD = password_hash(secrets.token_urlsafe(32))


@app.middleware("http")
async def request_boundary(request: Request, call_next):
    request_id = str(uuid4())
    request.state.request_id = request_id
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if request.headers.get("origin") != settings().public_origin.rstrip("/"):
            return JSONResponse({"code":"ORIGIN_REJECTED", "message":"请求来源无效", "request_id":request_id}, status_code=403)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    return JSONResponse({"code":f"HTTP_{exc.status_code}", "message":exc.detail,
                         "request_id":request.state.request_id}, status_code=exc.status_code)


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class NewAnalysis(BaseModel):
    scenario: str = Field(max_length=40)
    dataset_id: str | None = Field(default=None, max_length=36)
    scope: dict | None = None


class Simulation(BaseModel):
    changes: dict[str, str] = Field(max_length=8)


@app.get("/api/v1/health")
def health(db: DB):
    db.execute(text("SELECT 1"))
    return {"status":"ok", "capabilities":{"deterministic_analysis":True, "datasets":True, "durable_queue":True, "model_gateway":True, "model_configuration":"worker_only", "sandbox":False, "statistics":False}}


@app.post("/api/v1/auth/login")
def login(payload: Credentials, response: Response, db: DB):
    attempts = db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "login_attempt", AuditEvent.object_id == payload.username, AuditEvent.created_at > utcnow()-timedelta(minutes=15)))
    if attempts >= 10:
        raise HTTPException(429, "登录尝试过多，请 15 分钟后再试")
    user = db.scalar(select(User).where(User.username == payload.username))
    valid = password_matches(payload.password, user.password_hash if user else DUMMY_PASSWORD)
    db.add(AuditEvent(actor_id=user.id if user else None, action="login_attempt", object_id=payload.username, details={"success":bool(user and user.active and valid)}))
    if not user or not user.active or not valid:
        db.commit()
        raise HTTPException(401, "用户名或密码错误")
    raw, csrf = secrets.token_urlsafe(32), secrets.token_hex(32)
    db.add(LoginSession(token_hash=token_hash(raw), user_id=user.id, csrf=csrf, expires_at=utcnow()+timedelta(hours=settings().session_hours)))
    db.commit()
    response.set_cookie(COOKIE, raw, httponly=True, secure=settings().secure_cookie, samesite="strict", max_age=settings().session_hours*3600, path="/")
    return {"username":user.username, "role":user.role, "domains":user.domains, "csrf":csrf}


@app.get("/api/v1/me")
def me(request: Request, user: Identity):
    return {"username":user.username, "role":user.role, "domains":user.domains, "csrf":request.state.login.csrf}


@app.post("/api/v1/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: DB, user: Identity):
    db.delete(request.state.login)
    db.commit()
    response.delete_cookie(COOKIE, path="/")


@app.get("/api/v1/dashboard")
def dashboard(user: Identity):
    return [calculate(key) for key in SCENARIOS if key in user.domains]


@app.get("/api/v1/sessions")
def sessions(db: DB, user: Identity):
    records = db.scalars(select(AnalysisSession).where(AnalysisSession.owner_id == user.id, AnalysisSession.scenario.in_(user.domains)).order_by(AnalysisSession.created_at.desc()).limit(100))
    return [{"id":r.id, "title":r.title, "scenario":r.scenario, "created_at":r.created_at.isoformat()} for r in records]


@app.post("/api/v1/sessions", status_code=201)
def create_session(payload: NewAnalysis, db: DB, user: Identity):
    authorize(user, payload.scenario, write=True)
    if payload.dataset_id:
        dataset = dataset_owned(db, user, payload.dataset_id)
        if dataset.scenario != payload.scenario:
            raise HTTPException(422, '数据版本与业务线不匹配')
        try:
            snapshot = analyze(payload.scenario, dataset.rows, payload.scope or default_scope(dataset.rows), dataset.id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        snapshot['data_digest'] = dataset.digest
        snapshot['data_kind'] = '合成日聚合样例（非真实业务）' if dataset.source_kind=='synthetic' else '导入的日聚合数据'
    else:
        if payload.scope is not None:
            raise HTTPException(422, '固定样例不支持日期范围筛选')
        snapshot = calculate(payload.scenario)
    record = AnalysisSession(owner_id=user.id, scenario=payload.scenario, title=snapshot["title"], snapshot=snapshot)
    db.add(record)
    db.flush()
    db.add(AuditEvent(actor_id=user.id, action="analysis_created", object_id=record.id, details={"dataset_version":snapshot["dataset_version"]}))
    db.commit()
    return {"id":record.id, **record.snapshot}


@app.get("/api/v1/sessions/{session_id}")
def get_session(session_id: str, db: DB, user: Identity):
    record = owned(db, user, session_id)
    return {"id":record.id, **record.snapshot}


@app.post("/api/v1/sessions/{session_id}/simulate")
def simulate_session(session_id: str, payload: Simulation, db: DB, user: Identity):
    record = owned(db, user, session_id)
    authorize(user, record.scenario, write=True)
    try:
        result = simulate_snapshot(record.snapshot, payload.changes)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.add(AuditEvent(actor_id=user.id, action="simulation", object_id=record.id, details=result))
    db.commit()
    return result


@app.get("/api/v1/sessions/{session_id}/report.md", response_class=PlainTextResponse)
def markdown_report(session_id: str, db: DB, user: Identity):
    record = owned(db, user, session_id)
    s, b = record.snapshot, record.snapshot["breakdown"]
    rows = [f"# {s['title']}\n", "状态：数学分解草稿，未完成统计归因验证。\n",
            f"数据：{s['dataset_version']}；算法：{s['algorithm_version']}\n",
            f"基期：{b['baseline']}；现期：{b['current']}；差额：{b['delta']} {b['unit']}\n",
            "| 因子 | 贡献量 |\n| --- | ---: |"]
    rows.extend(f"| {f['label']} | {f['contribution']} |" for f in b["factors"])
    if 'scope' in s:
        scope=s['scope']
        rows += ['\n## 数据范围\n',f"类型：{s['data_kind']}；SHA-256：{s.get('data_digest','')}\n",
                 f"基期：{' 至 '.join(scope['baseline'])}；现期：{' 至 '.join(scope['current'])}\n",
                 f"筛选：{scope['filters']}；分组：{scope['group_by']}\n"]
    rows += ["\n## 分析边界\n", *s["limitations"], "\n本草稿不包含尚未执行的检验、事件因果证明或收益区间。"]
    db.add(AuditEvent(actor_id=user.id, action="report_exported", object_id=record.id))
    db.commit()
    return PlainTextResponse("\n".join(rows), headers={"Content-Disposition":f'attachment; filename="analysis-{record.id}.md"'})
