"""HTTP endpoints for analysis sessions and their draft reports."""
from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from typing import Annotated
from pydantic import StringConstraints
from sqlalchemy import select

from ...access import DB, Identity, authorize, owned
from ...db import AnalysisSession, AuditEvent
from ...domain.scenarios import SCENARIOS, calculate
from ...domain.monitoring import compare
from ...domain.metric_catalog import catalog
from ...domain.sensitivity import capture_formula_sensitivity, formula_sensitivity
from ...domain.variability import baseline_variability
from ..datasets.access import dataset_owned
from ..events.matching import report_view
from . import service
from .snapshot import analysis_revision, drilldown_revision, report_revision, serialize_session
from .report import markdown_report_text
from .report_evidence import capture_variability
from .exporters import pdf, spreadsheet

router = APIRouter(prefix="/api/v1", tags=["analysis"])


class NewAnalysis(BaseModel):
    scenario: str = Field(min_length=1, max_length=40)
    dataset_id: str | None = Field(default=None, min_length=1, max_length=36)
    scope: dict | None = None


class Simulation(BaseModel):
    changes: dict[str, str] = Field(max_length=8)


class SimulationScenario(BaseModel):
    name: str = Field(min_length=1, max_length=80, pattern=r'.*\S.*')
    changes: dict[str, str] = Field(min_length=1, max_length=8)


class SimulationComparison(BaseModel):
    revision: str = Field(min_length=64, max_length=64, pattern=r'^[0-9a-f]{64}$')
    draft_revision: str = Field(min_length=64, max_length=64, pattern=r'^[0-9a-f]{64}$')
    scenarios: list[SimulationScenario] = Field(min_length=1, max_length=5)


class SimulationPreview(BaseModel):
    revision: str = Field(min_length=64, max_length=64, pattern=r'^[0-9a-f]{64}$')
    scenarios: list[SimulationScenario] = Field(min_length=1, max_length=5)


class ActionItem(BaseModel):
    action: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    factor_key: str = Field(min_length=1, max_length=64)
    owner_role: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] = ''
    estimated_days: int | None = Field(default=None, ge=1, le=3650)
    estimated_benefit: str | None = Field(default=None, min_length=1, max_length=64)
    benefit_basis: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ''


class ActionList(BaseModel):
    revision: str = Field(min_length=64, max_length=64, pattern=r'^[0-9a-f]{64}$')
    draft_revision: str = Field(min_length=64, max_length=64, pattern=r'^[0-9a-f]{64}$')
    items: list[ActionItem] = Field(max_length=10)


class DailyCheck(BaseModel):
    revision: str = Field(min_length=64, max_length=64, pattern=r'^[0-9a-f]{64}$')
    draft_revision: str = Field(min_length=64, max_length=64, pattern=r'^[0-9a-f]{64}$')
    confidence_level: float = Field(ge=0.8, le=0.99, allow_inf_nan=False)
    factor_key: str | None = Field(default=None, max_length=64)
    group_value: str | None = Field(default=None, min_length=1, max_length=60)


class ReportNote(BaseModel):
    revision: str = Field(min_length=64, max_length=64, pattern=r'^[0-9a-f]{64}$')
    text: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000,
                                           pattern=r'^[^\x00-\x08\x0b\x0c\x0e-\x1f]*$')]


class Comparison(BaseModel):
    scope: dict
    threshold: str = Field(min_length=1, max_length=40)


class DrilldownExport(BaseModel):
    dataset_version: str = Field(min_length=1, max_length=80)
    scope: dict
    revision: str = Field(min_length=64, max_length=64, pattern=r'^[0-9a-f]{64}$')


@router.get("/dashboard")
def dashboard(user: Identity):
    return [calculate(key) for key in SCENARIOS if key in user.domains]


@router.post("/datasets/{dataset_id}/compare")
def compare_dataset(dataset_id: str, payload: Comparison, db: DB, user: Identity):
    dataset = dataset_owned(db, user, dataset_id)
    try:
        result = compare(dataset.scenario, dataset.rows, payload.scope, payload.threshold)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    result['dataset_version'] = dataset.id
    result['data_digest'] = dataset.digest
    db.add(AuditEvent(actor_id=user.id, action="metric_compared", object_id=dataset.id,
                      details={'scope': result['scope'], 'threshold': result['threshold'],
                               'threshold_unit': result['threshold_unit'], 'status': result['status']}))
    db.commit()
    return result


@router.get("/metrics/{scenario}")
def metric_catalog(scenario: str, user: Identity):
    authorize(user, scenario)
    return catalog(scenario)


@router.get("/sessions")
def sessions(db: DB, user: Identity):
    records = db.scalars(select(AnalysisSession).where(
        AnalysisSession.owner_id == user.id, AnalysisSession.scenario.in_(user.domains)
    ).order_by(AnalysisSession.created_at.desc()).limit(100))
    return [{"id": r.id, "title": r.title, "scenario": r.scenario,
             "created_at": r.created_at.isoformat()} for r in records]


@router.post("/sessions", status_code=201)
def create_session(payload: NewAnalysis, db: DB, user: Identity):
    return service.create(db, user, payload.scenario, payload.dataset_id, payload.scope)


@router.get("/sessions/{session_id}")
def get_session(session_id: str, db: DB, user: Identity):
    record = owned(db, user, session_id)
    return serialize_session(record)


@router.put('/sessions/{session_id}/report-note')
def save_report_note(session_id: str, payload: ReportNote, db: DB, user: Identity):
    from ...db import utcnow
    record = owned(db, user, session_id, lock=True)
    authorize(user, record.scenario, write=True)
    if report_revision(record.snapshot) != payload.revision:
        raise HTTPException(409, '报告内容已更新，请保留输入并刷新后核对')
    note = {'text': payload.text, 'author': user.username, 'updated_at': utcnow().isoformat()} if payload.text else None
    record.snapshot = {**record.snapshot, 'report_note': note}
    db.add(AuditEvent(actor_id=user.id, action='report_note_saved', object_id=record.id,
                      details={'cleared': note is None, 'previous_revision': payload.revision}))
    db.commit()
    return serialize_session(record)


@router.get("/sessions/{session_id}/formula-sensitivity")
def get_formula_sensitivity(session_id: str, db: DB, user: Identity):
    record = owned(db, user, session_id)
    try:
        result = formula_sensitivity(record.snapshot)
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        raise HTTPException(422, '该快照缺少计算公式敏感性所需的参数') from exc
    return {**result, 'analysis_revision':analysis_revision(record.snapshot)}


@router.get("/sessions/{session_id}/baseline-variability")
def get_baseline_variability(session_id: str, db: DB, user: Identity):
    record = owned(db, user, session_id)
    scope = record.snapshot.get('scope')
    if not scope:
        raise HTTPException(422, '固定汇总样例没有逐日数据，无法计算历史波动')
    dataset = dataset_owned(db, user, record.snapshot.get('dataset_version'))
    if dataset.scenario != record.scenario or dataset.digest != record.snapshot.get('data_digest'):
        raise HTTPException(409, '数据版本与分析不一致，无法计算历史波动')
    try:
        result = baseline_variability(record.scenario, dataset.rows, scope)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {**result, 'analysis_revision':analysis_revision(record.snapshot),
            'dataset_version':dataset.id, 'data_digest':dataset.digest}


@router.post("/sessions/{session_id}/simulate")
def simulate_session(session_id: str, payload: Simulation, db: DB, user: Identity):
    return service.simulate(db, user, session_id, payload.changes)


@router.post("/sessions/{session_id}/simulation-comparison")
def simulation_comparison(session_id: str, payload: SimulationComparison, db: DB, user: Identity):
    return service.compare_simulations(db, user, session_id, payload.revision, payload.draft_revision, payload.scenarios)


@router.post("/sessions/{session_id}/simulation-preview")
def simulation_preview(session_id: str, payload: SimulationPreview, db: DB, user: Identity):
    return service.preview_simulations(db, user, session_id, payload.revision, payload.scenarios)


@router.put("/sessions/{session_id}/action-items")
def update_action_items(session_id: str, payload: ActionList, db: DB, user: Identity):
    return service.save_action_items(db, user, session_id, payload.revision, payload.draft_revision, payload.items)


@router.post("/sessions/{session_id}/daily-statistical-check")
def daily_statistical_check(session_id: str, payload: DailyCheck, db: DB, user: Identity):
    return service.run_daily_check(db, user, session_id, payload.revision, payload.draft_revision, payload.confidence_level, payload.factor_key, payload.group_value)


@router.post("/sessions/{session_id}/drilldown-export", status_code=204)
def audit_drilldown_export(session_id: str, payload: DrilldownExport, db: DB, user: Identity):
    record = owned(db, user, session_id)
    if not record.snapshot.get('drilldown'):
        raise HTTPException(409, '当前分析没有可导出的分组数据')
    if (record.snapshot.get('dataset_version') != payload.dataset_version
            or record.snapshot.get('scope') != payload.scope
            or drilldown_revision(record.snapshot) != payload.revision):
        raise HTTPException(409, '分析结果已更新，请刷新结果后重新导出')
    db.add(AuditEvent(actor_id=user.id, action='drilldown_export_requested', object_id=record.id,
                      details={'dataset_version': payload.dataset_version, 'scope': payload.scope,
                               'revision': payload.revision}))
    db.commit()
    return Response(status_code=204)


@router.get("/sessions/{session_id}/report.md", response_class=PlainTextResponse)
def markdown_report(session_id: str, db: DB, user: Identity):
    record = owned(db, user, session_id)
    events = report_view(db, user, record)
    text = markdown_report_text({**record.snapshot, 'report_events': events, 'report_sensitivity':capture_formula_sensitivity(record.snapshot),
                                 'report_variability':capture_variability(db, user, record)})
    db.add(AuditEvent(actor_id=user.id, action="report_exported", object_id=record.id,
                      details={'format': 'markdown', 'events_checked_at': events['checked_at'],
                               'event_count': len(events['events']), 'events_truncated': events['truncated']}))
    db.commit()
    return PlainTextResponse(text, headers={"Content-Disposition": f'attachment; filename="analysis-{record.id}.md"'})


@router.get('/sessions/{session_id}/report-preview')
def report_preview(session_id: str, db: DB, user: Identity,
                   revision: str = Query(min_length=64, max_length=64, pattern=r'^[0-9a-f]{64}$')):
    record = owned(db, user, session_id)
    if report_revision(record.snapshot) != revision:
        raise HTTPException(409, '报告内容已更新，请重新打开会话后预览')
    events = report_view(db, user, record)
    text = markdown_report_text({**record.snapshot, 'report_events': events,
                                 'report_sensitivity': capture_formula_sensitivity(record.snapshot),
                                 'report_variability': capture_variability(db, user, record)})
    db.add(AuditEvent(actor_id=user.id, action='report_previewed', object_id=record.id,
                      details={'revision': revision, 'events_checked_at': events['checked_at'],
                               'event_count': len(events['events']), 'events_truncated': events['truncated']}))
    db.commit()
    return {'revision': revision, 'markdown': text, 'events_checked_at': events['checked_at']}


@router.get("/sessions/{session_id}/report.xlsx")
def spreadsheet_report(session_id: str, db: DB, user: Identity):
    record = owned(db, user, session_id)
    events = report_view(db, user, record)
    content = spreadsheet({**record.snapshot, 'report_events': events, 'report_sensitivity':capture_formula_sensitivity(record.snapshot),
                           'report_variability':capture_variability(db, user, record)})
    db.add(AuditEvent(actor_id=user.id, action='report_exported', object_id=record.id,
                      details={'format':'xlsx', 'events_checked_at':events['checked_at'],
                               'event_count':len(events['events']), 'events_truncated':events['truncated']}))
    db.commit()
    return Response(content, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition': f'attachment; filename="analysis-{record.id}.xlsx"'})


@router.get("/sessions/{session_id}/report.pdf")
def pdf_report(session_id: str, db: DB, user: Identity):
    record = owned(db, user, session_id)
    events = report_view(db, user, record)
    try:
        content = pdf({**record.snapshot, 'report_events': events, 'report_sensitivity':capture_formula_sensitivity(record.snapshot),
                       'report_variability':capture_variability(db, user, record)})
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    db.add(AuditEvent(actor_id=user.id, action='report_exported', object_id=record.id,
                      details={'format':'pdf', 'events_checked_at':events['checked_at'],
                               'event_count':len(events['events']), 'events_truncated':events['truncated']}))
    db.commit()
    return Response(content, media_type='application/pdf',
                    headers={'Content-Disposition': f'attachment; filename="analysis-{record.id}.pdf"'})
