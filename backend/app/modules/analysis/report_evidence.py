"""Capture authorized report evidence before rendering or freezing an archive."""
from fastapi import HTTPException

from ...domain.variability import baseline_variability
from ..datasets.access import dataset_owned


def capture_variability(db, user, session):
    snapshot = session.snapshot
    if not snapshot.get('scope') or snapshot.get('dataset_version') == 'prd-fixture-v1':
        return {'status':'unavailable', 'notice':'该快照没有可用的逐日数据，无法计算基期波动。'}
    try:
        dataset = dataset_owned(db, user, snapshot.get('dataset_version'))
    except HTTPException as exc:
        if exc.status_code == 404:
            return {'status':'unavailable', 'notice':'原数据版本不可用，无法计算基期波动。'}
        raise
    if dataset.scenario != session.scenario or dataset.digest != snapshot.get('data_digest'):
        return {'status':'unavailable', 'notice':'数据版本或摘要不一致，无法计算基期波动。'}
    try:
        result = baseline_variability(session.scenario, dataset.rows, snapshot['scope'])
    except ValueError:
        return {'status':'unavailable', 'notice':'数据范围或精度不支持基期波动计算。'}
    return {'status':'available', 'dataset_version':dataset.id, 'data_digest':dataset.digest, **result}
