from datetime import datetime, timezone
from uuid import uuid4
from decimal import Decimal
from sqlalchemy import create_engine, DateTime, String, ForeignKey, JSON, Index, Integer, Numeric, Text, UniqueConstraint, CheckConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from .config import settings


def utcnow():
    return datetime.now(timezone.utc)


def identifier():
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(24), default="analyst")
    domains: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(default=True)


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    csrf: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AnalysisSession(Base):
    __tablename__ = "analysis_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    scenario: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(160))
    snapshot: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReportArchive(Base):
    __tablename__ = 'report_archives'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    session_id: Mapped[str] = mapped_column(ForeignKey('analysis_sessions.id'))
    scenario: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(160))
    snapshot: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (Index('ix_report_archives_owner_session_created', 'owner_id', 'session_id', 'created_at'),)


class ReportPublication(Base):
    __tablename__ = 'report_publications'
    report_id: Mapped[str] = mapped_column(ForeignKey('report_archives.id'), primary_key=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    active: Mapped[bool] = mapped_column(default=True)


class ReportComment(Base):
    __tablename__ = 'report_comments'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    report_id: Mapped[str] = mapped_column(ForeignKey('report_archives.id'))
    author_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    body: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (Index('ix_report_comments_report_created', 'report_id', 'created_at', 'id'),)


class BriefSubscription(Base):
    __tablename__ = 'brief_subscriptions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    scenario: Mapped[str] = mapped_column(String(40))
    frequency: Mapped[str] = mapped_column(String(10))
    active: Mapped[bool] = mapped_column(default=True)
    last_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    next_due: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint('user_id', 'scenario', name='uq_brief_subscription_user_scenario'),
                      Index('ix_brief_subscription_due', 'active', 'next_due'))


class BriefIssue(Base):
    __tablename__ = 'brief_issues'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    subscription_id: Mapped[str] = mapped_column(ForeignKey('brief_subscriptions.id'))
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    report_ids: Mapped[list] = mapped_column(JSON)
    truncated: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (Index('ix_brief_issue_subscription_created', 'subscription_id', 'created_at'),)


class MetricDraft(Base):
    __tablename__ = 'metric_drafts'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    author_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    scenario: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(120))
    definitions: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (Index('ix_metric_drafts_scenario_created', 'scenario', 'created_at'),)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    object_id: Mapped[str] = mapped_column(String(160), default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (Index("ix_audit_action_object_time", "action", "object_id", "created_at"),)


class BusinessEvent(Base):
    __tablename__ = 'business_events'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    scenario: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(160))
    start: Mapped[str] = mapped_column(String(10))
    end: Mapped[str] = mapped_column(String(10))
    scope: Mapped[dict] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DatasetVersion(Base):
    __tablename__ = 'dataset_versions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    scenario: Mapped[str] = mapped_column(String(40), index=True)
    name: Mapped[str] = mapped_column(String(120))
    source_kind: Mapped[str] = mapped_column(String(16),default='imported')
    digest: Mapped[str] = mapped_column(String(64))
    rows: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint('owner_id','scenario','digest',name='uq_dataset_digest'),)


class AnalysisRun(Base):
    __tablename__ = 'analysis_runs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    session_id: Mapped[str] = mapped_column(ForeignKey('analysis_sessions.id'), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    dataset_id: Mapped[str] = mapped_column(ForeignKey('dataset_versions.id'))
    request_key: Mapped[str] = mapped_column(String(80))
    request_hash: Mapped[str] = mapped_column(String(64))
    question: Mapped[str] = mapped_column(String(2000))
    scope: Mapped[dict] = mapped_column(JSON)
    parents: Mapped[list] = mapped_column(JSON, default=list)
    mode: Mapped[str] = mapped_column(String(16), default='rules')
    status: Mapped[str] = mapped_column(String(24), default='queued')
    stage: Mapped[str] = mapped_column(String(60), default='queued')
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    fence: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        UniqueConstraint('owner_id','request_key',name='uq_run_request'),
        Index('uq_run_active_session','session_id',unique=True,postgresql_where=text("status IN ('queued','running')")),
    )


class RunEvent(Base):
    __tablename__ = 'run_events'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    run_id: Mapped[str] = mapped_column(ForeignKey('analysis_runs.id'), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint('run_id','sequence',name='uq_run_event'),)


class BudgetAccount(Base):
    __tablename__ = 'budget_accounts'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    limit_cny: Mapped[Decimal] = mapped_column(Numeric(18,8), default=Decimal('25'))
    spent_cny: Mapped[Decimal] = mapped_column(Numeric(18,8), default=Decimal('0'))
    reserved_cny: Mapped[Decimal] = mapped_column(Numeric(18,8), default=Decimal('0'))
    __table_args__ = (CheckConstraint('limit_cny>=0 AND spent_cny>=0 AND reserved_cny>=0',name='ck_budget_nonnegative'),)


class ModelCall(Base):
    __tablename__ = 'model_calls'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    run_id: Mapped[str] = mapped_column(ForeignKey('analysis_runs.id'))
    state: Mapped[str] = mapped_column(String(24), default='reserved')
    reserved_cny: Mapped[Decimal] = mapped_column(Numeric(18,8))
    actual_cny: Mapped[Decimal | None] = mapped_column(Numeric(18,8), nullable=True)
    price_version: Mapped[str] = mapped_column(String(80))
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


engine = create_engine(settings().database_url, pool_pre_ping=True)
SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)


def database():
    with SessionFactory() as session:
        yield session
