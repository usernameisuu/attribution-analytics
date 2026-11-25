"""Application operations for creating and simulating analysis sessions."""
from fastapi import HTTPException
from decimal import Decimal

from ...access import authorize, owned
from ...db import AnalysisSession, AuditEvent, utcnow
from ...domain.exploration import analyze, default_scope, simulate_snapshot
from ...domain.scenarios import calculate
from ...domain.attribution import number
from ...domain.statistical_checks import daily_welch
from ..datasets.access import dataset_owned
from .snapshot import analysis_revision, draft_revision, serialize_session


def create(db, user, scenario, dataset_id, scope):
    authorize(user, scenario, write=True)
    if dataset_id:
        dataset = dataset_owned(db, user, dataset_id)
        if dataset.scenario != scenario:
            raise HTTPException(422, "数据版本与业务线不匹配")
        try:
            selected_scope = default_scope(dataset.rows) if scope is None else scope
            snapshot = analyze(scenario, dataset.rows, selected_scope, dataset.id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        snapshot["data_digest"] = dataset.digest
        snapshot["data_kind"] = (
            "合成日聚合样例（非真实业务）" if dataset.source_kind == "synthetic" else "导入的日聚合数据"
        )
    else:
        if scope is not None:
            raise HTTPException(422, "固定样例不支持日期范围筛选")
        snapshot = calculate(scenario)
    record = AnalysisSession(owner_id=user.id, scenario=scenario, title=snapshot["title"], snapshot=snapshot)
    db.add(record)
    db.flush()
    db.add(AuditEvent(actor_id=user.id, action="analysis_created", object_id=record.id,
                      details={"dataset_version": snapshot["dataset_version"]}))
    db.commit()
    return serialize_session(record)


def simulate(db, user, session_id, changes):
    record = owned(db, user, session_id)
    authorize(user, record.scenario, write=True)
    try:
        result = simulate_snapshot(record.snapshot, changes)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.add(AuditEvent(actor_id=user.id, action="simulation", object_id=record.id, details=result))
    db.commit()
    return result


def _calculate_scenarios(snapshot, scenarios):
    results = []
    for scenario in scenarios:
        try:
            result = simulate_snapshot(snapshot, scenario.changes)
        except ValueError as exc:
            raise HTTPException(422, f'情景「{scenario.name}」：{exc}') from exc
        results.append({'name': scenario.name, 'changes': scenario.changes, **result})
    return results


def preview_simulations(db, user, session_id, revision, scenarios):
    record = owned(db, user, session_id)
    authorize(user, record.scenario, write=True)
    if analysis_revision(record.snapshot) != revision:
        raise HTTPException(409, '分析结果已更新，请刷新后重新模拟')
    return _calculate_scenarios(record.snapshot, scenarios)


def compare_simulations(db, user, session_id, revision, expected_draft, scenarios):
    record = owned(db, user, session_id, lock=True)
    authorize(user, record.scenario, write=True)
    if analysis_revision(record.snapshot) != revision:
        raise HTTPException(409, '分析结果已更新，请刷新后重新模拟')
    if draft_revision(record.snapshot, 'simulation_scenarios') != expected_draft:
        raise HTTPException(409, '情景对比已被更新，请保留当前输入并刷新后核对')
    results = _calculate_scenarios(record.snapshot, scenarios)
    record.snapshot = {**record.snapshot, 'simulation_scenarios': results}
    db.add(AuditEvent(actor_id=user.id, action='simulation_comparison_saved', object_id=record.id,
                      details={'analysis_revision': revision, 'scenarios': results}))
    db.commit()
    return serialize_session(record)


def save_action_items(db, user, session_id, revision, expected_draft, items):
    record = owned(db, user, session_id, lock=True)
    authorize(user, record.scenario, write=True)
    if analysis_revision(record.snapshot) != revision:
        raise HTTPException(409, '分析结果已更新，请刷新后重新编辑行动清单')
    if draft_revision(record.snapshot, 'action_items') != expected_draft:
        raise HTTPException(409, '行动清单已被更新，请保留当前输入并刷新后核对')
    factors = {factor['key']: factor for factor in record.snapshot['breakdown']['factors']}
    actions = []
    for item in items:
        factor = factors.get(item.factor_key)
        if not factor:
            raise HTTPException(422, '行动关联的驱动因子不存在')
        benefit = None
        if item.estimated_benefit is not None:
            try:
                value = number(item.estimated_benefit)
            except ValueError as exc:
                raise HTTPException(422, '预计收益必须是有限数值') from exc
            if abs(value) > Decimal('1e15'):
                raise HTTPException(422, '预计收益超出允许范围')
            if not item.benefit_basis:
                raise HTTPException(422, '填写预计收益时必须说明估算依据')
            benefit = str(value)
        actions.append({'action': item.action, 'factor_key': item.factor_key,
                        'factor_label': factor['label'], 'factor_contribution': factor['contribution'],
                        'owner_role': item.owner_role, 'estimated_days': item.estimated_days,
                        'estimated_benefit': benefit, 'benefit_basis': item.benefit_basis,
                        'source': 'analyst'})
    record.snapshot = {**record.snapshot, 'action_items': actions}
    db.add(AuditEvent(actor_id=user.id, action='action_items_saved', object_id=record.id,
                      details={'analysis_revision': revision, 'items': actions}))
    db.commit()
    return serialize_session(record)


def run_daily_check(db, user, session_id, revision, expected_draft, confidence_level, factor_key=None, group_value=None):
    record = owned(db, user, session_id, lock=True)
    authorize(user, record.scenario, write=True)
    if analysis_revision(record.snapshot) != revision:
        raise HTTPException(409, '分析结果已更新，请刷新后重新检验')
    if draft_revision(record.snapshot, 'statistical_checks') != expected_draft:
        raise HTTPException(409, '检验记录已被更新，请刷新后核对')
    scope = record.snapshot.get('scope')
    if not scope:
        raise HTTPException(422, '固定汇总样例没有逐日数据，无法执行此检验')
    dataset = dataset_owned(db, user, record.snapshot.get('dataset_version'))
    if dataset.scenario != record.scenario or dataset.digest != record.snapshot.get('data_digest'):
        raise HTTPException(409, '数据版本与当前分析不一致，无法检验')
    try:
        result = daily_welch(record.scenario, dataset.rows, scope, confidence_level, factor_key, group_value)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    from scipy import __version__ as scipy_version
    result.update(dataset_version=dataset.id, data_digest=dataset.digest,
                  calculated_at=utcnow().isoformat(), method_version='daily-welch-v5', scipy_version=scipy_version)
    # Keep one latest check per selected metric; repeating a metric replaces it.
    # Legacy checks have no factor key and belong to the overall metric.
    checks = [check for check in record.snapshot.get('statistical_checks', [])
              if (check.get('factor_key'), check.get('group_value')) != (factor_key, group_value)]
    if len(checks) >= 50:
        raise HTTPException(422, '每个分析最多保留 50 项不同检验')
    record.snapshot = {**record.snapshot, 'statistical_checks': [*checks, result]}
    db.add(AuditEvent(actor_id=user.id, action='statistical_check_saved', object_id=record.id,
                      details={'analysis_revision':revision, 'dataset_version':dataset.id,
                               'data_digest':dataset.digest, 'method':result['method'], 'factor_key':factor_key,
                               'group_value':group_value, 'group_dimension':result['group_dimension'],
                               'method_version':result['method_version'], 'status':result['status']}))
    db.commit()
    return serialize_session(record)
