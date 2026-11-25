"""Administrator-only metric definition drafts; never activated by this API."""
from copy import deepcopy
import hashlib
import json
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import select

from ...access import DB, Identity, administrator
from ...db import AuditEvent, MetricDraft
from ...domain.metric_catalog import catalog
from ...domain.metric_expressions import evaluate, validate_definitions
from ...domain.metric_comparison import compare_synthetic

router = APIRouter(prefix='/api/v1/admin/metric-drafts', tags=['metric drafts'])
_VALIDATION_MESSAGES = {
    'invalid metric name':'指标标识无效，请使用小写字母、数字和下划线',
    'invalid unit':'单位定义格式无效',
    'invalid unit exponent':'单位指数无效',
    'unit exponent exceeds limit':'组合后的单位指数超出范围',
    'invalid metric definitions':'指标定义数量或格式无效',
    'metric cycle':'指标依赖存在循环',
    'unknown metric reference':'公式引用了不存在的指标',
    'invalid metric definition':'指标定义字段无效',
    'declared unit does not match expression':'声明单位与公式计算单位不一致',
    'expression exceeds limits or is invalid':'表达式格式无效或超过复杂度限制',
    'numeric values must be decimal strings':'常量必须使用十进制字符串',
    'invalid number':'常量数值格式无效',
    'number outside supported range':'常量数值超出支持范围',
    'unsupported expression':'公式包含不支持的操作',
    'incompatible units':'加减运算的单位不一致',
    '指标定义超过大小限制':'指标定义超过大小限制',
    '场景根指标缺失、无公式或单位不匹配':'场景根指标缺失、无公式或单位不匹配',
    'invalid metric definitions or inputs':'指标定义或输入格式无效',
    'missing aggregated input':'缺少公式所需的输入指标',
    'division by zero':'公式分母为零，无法计算',
    'metric arithmetic failed':'指标运算失败',
    'metric result outside supported range':'计算结果超出支持范围',
    'invalid input metric':'输入只能包含已定义的原子指标',
    '仅支持比较当前业务场景的根指标':'仅支持比较当前业务场景的根指标',
    '合成数据比较缺少目标指标':'合成数据比较缺少目标指标',
    '合成数据未提供所需原子指标':'合成数据未提供所需原子指标',
    '合成数据原子指标单位不匹配':'合成数据原子指标单位不匹配',
}


class MetricDraftInput(BaseModel):
    scenario: Literal['ecommerce', 'consumer']
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120,
                                            pattern=r'^[^\x00-\x1f]+$')]
    definitions: dict = Field(min_length=1, max_length=100)


class MetricPreviewInput(BaseModel):
    target: Annotated[str, StringConstraints(min_length=1, max_length=64, pattern=r'^[a-z][a-z0-9_]*$')]
    inputs: dict[str, str] = Field(max_length=100)


class SyntheticComparisonInput(BaseModel):
    target: Annotated[str, StringConstraints(min_length=1, max_length=64, pattern=r'^[a-z][a-z0-9_]*$')]


def metadata(record):
    return {'id':record.id, 'scenario':record.scenario, 'name':record.name,
            'digest':record.digest, 'author_id':record.author_id,
            'created_at':record.created_at.isoformat(), 'status':'draft'}


def definition_bytes(definitions):
    return json.dumps(definitions, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


@router.get('/template/{scenario}')
def template(scenario: Literal['ecommerce','consumer'], user: Identity):
    administrator(user)
    data = catalog(scenario)
    return {'scenario':scenario, 'base_version':data['version'], 'definitions':data['definitions']}


@router.get('')
def list_drafts(db: DB, user: Identity, scenario: Literal['ecommerce','consumer']):
    administrator(user)
    records = db.scalars(select(MetricDraft).where(MetricDraft.scenario==scenario)
                         .order_by(MetricDraft.created_at.desc(),MetricDraft.id.desc()).limit(100))
    return [metadata(record) for record in records]


@router.get('/{draft_id}')
def get_draft(draft_id: str, db: DB, user: Identity):
    administrator(user)
    record = db.get(MetricDraft, draft_id)
    if not record:
        raise HTTPException(404, '指标草稿不存在')
    try:
        digest = hashlib.sha256(definition_bytes(record.definitions)).hexdigest()
    except (TypeError, ValueError, RecursionError) as exc:
        raise HTTPException(409, '指标草稿内容校验失败') from exc
    if digest != record.digest:
        raise HTTPException(409, '指标草稿内容校验失败')
    return {**metadata(record), 'definitions':deepcopy(record.definitions)}


@router.post('/{draft_id}/preview')
def preview_draft(draft_id: str, payload: MetricPreviewInput, db: DB, user: Identity):
    draft = get_draft(draft_id, db, user)
    definitions = draft['definitions']
    try:
        if any(key not in definitions or definitions[key]['expression'] is not None for key in payload.inputs):
            raise ValueError('invalid input metric')
        for key, value in payload.inputs.items():
            evaluate(definitions, {key:value}, key)
        result = evaluate(definitions, payload.inputs, payload.target)
    except (KeyError, TypeError, ValueError, RecursionError) as exc:
        message = _VALIDATION_MESSAGES.get(str(exc), '指标定义或输入格式无效')
        raise HTTPException(422, f'指标试算失败：{message}') from exc
    db.add(AuditEvent(actor_id=user.id, action='metric_draft_previewed', object_id=draft_id,
                      details={'digest':draft['digest'], 'target':payload.target}))
    db.commit()
    return {'draft_id':draft_id, 'digest':draft['digest'], 'target':payload.target,
            'value':str(result['value']), 'unit':result['unit'],
            'notice':'试算使用手工输入，Decimal 精度为 38 位，除法可能舍入；不启用草稿，也不验证业务口径。'}


@router.post('/{draft_id}/compare-synthetic')
def compare_draft_synthetic(draft_id: str, payload: SyntheticComparisonInput, db: DB, user: Identity):
    draft = get_draft(draft_id, db, user)
    try:
        result = compare_synthetic(draft['scenario'], draft['definitions'], payload.target)
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        message = _VALIDATION_MESSAGES.get(str(exc), '合成数据不满足该公式或计算条件')
        raise HTTPException(422, f'指标比较失败：{message}') from exc
    result['comparison_version'] = 'synthetic-compare-v1'
    result_digest = hashlib.sha256(definition_bytes(result)).hexdigest()
    event = AuditEvent(actor_id=user.id, action='metric_draft_synthetic_compared', object_id=draft_id,
                       details={'digest':draft['digest'], 'target':payload.target, 'data_digest':result['data_digest'],
                                'comparison':deepcopy(result), 'result_digest':result_digest})
    db.add(event)
    db.flush()
    db.commit()
    return {'record_id':event.id, 'result_digest':result_digest, 'draft_id':draft_id,
            'draft_digest':draft['digest'], **result}


@router.get('/{draft_id}/comparisons')
def comparison_history(draft_id: str, db: DB, user: Identity):
    draft = get_draft(draft_id, db, user)
    events = db.scalars(select(AuditEvent).where(AuditEvent.object_id==draft_id,
                        AuditEvent.action=='metric_draft_synthetic_compared')
                        .order_by(AuditEvent.created_at.desc(),AuditEvent.id.desc()).limit(50))
    history = []
    for event in events:
        details = event.details if isinstance(event.details,dict) else {}
        result = details.get('comparison')
        record = {'id':event.id, 'created_at':event.created_at.isoformat(), 'actor_id':event.actor_id,
                  'target':details.get('target'), 'status':'unavailable', 'result':None}
        if isinstance(result,dict):
            try:
                valid = (details.get('digest')==draft['digest'] and
                         details.get('target')==result.get('target') and
                         details.get('data_digest')==result.get('data_digest') and
                         hashlib.sha256(definition_bytes(result)).hexdigest()==details.get('result_digest'))
            except (TypeError, ValueError, RecursionError):
                valid = False
            if valid:
                record.update(status='available', result=deepcopy(result))
            else:
                record['status']='corrupt'
        elif 'comparison' in details or 'result_digest' in details:
            # Legacy events contain neither field. A partial new record must not
            # be mistaken for an old event whose result was never saved.
            record['status']='corrupt'
        history.append(record)
    return history


@router.post('', status_code=201)
def create_draft(payload: MetricDraftInput, db: DB, user: Identity):
    administrator(user)
    try:
        encoded = definition_bytes(payload.definitions)
        if len(encoded) > 100_000:
            raise ValueError('指标定义超过大小限制')
        validate_definitions(payload.definitions)
        base = catalog(payload.scenario)
        roots = [base['scenario_metric']['metric']]
        if base['scenario_metric'].get('margin_metric'):
            roots.append(base['scenario_metric']['margin_metric'])
        for root in roots:
            definition = payload.definitions.get(root)
            if (not definition or definition.get('expression') is None
                    or definition.get('unit') != base['definitions'][root]['unit']):
                raise ValueError('场景根指标缺失、无公式或单位不匹配')
    except (TypeError, ValueError, RecursionError) as exc:
        message = _VALIDATION_MESSAGES.get(str(exc), '指标定义格式无效')
        raise HTTPException(422, f'指标草稿校验失败：{message}') from exc
    digest = hashlib.sha256(encoded).hexdigest()
    record = MetricDraft(author_id=user.id, scenario=payload.scenario, name=payload.name,
                         definitions=deepcopy(payload.definitions), digest=digest)
    db.add(record)
    db.flush()
    db.add(AuditEvent(actor_id=user.id, action='metric_draft_created', object_id=record.id,
                      details={'scenario':payload.scenario, 'digest':digest, 'active':False}))
    db.commit()
    return metadata(record)
