"""Authorization-aware lookup of private dataset versions."""
from fastapi import HTTPException

from ...access import authorize
from ...db import DatasetVersion


def dataset_owned(db, user, dataset_id):
    record = db.get(DatasetVersion, dataset_id)
    if not record or record.owner_id != user.id:
        raise HTTPException(404, "数据版本不存在或无权访问")
    authorize(user, record.scenario)
    return record
