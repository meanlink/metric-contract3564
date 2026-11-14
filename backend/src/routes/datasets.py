from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from src.config.database import get_db
from src.models import Dataset
from src.schemas.dataset import DatasetInput, SupplementInput
from src.middlewares.auth import current_user, can_write
from src.services import datasets
from src.services.audit import record
from src.utils.serialization import dataset_dict
router=APIRouter(prefix='/datasets')
@router.get('')
def listing(db=Depends(get_db),u=Depends(current_user)):
    return [dataset_dict(d) for d in db.scalars(select(Dataset).order_by(Dataset.id.desc()))]
@router.post('',status_code=201)
def create(data:DatasetInput,db=Depends(get_db),u=Depends(can_write)):
    d=datasets.create(db,data); record(db,u.email,'dataset.create',{'id':d.id,'rows':len(d.records)})
    db.commit(); return dataset_dict(d)
@router.post('/{id}/supplement',status_code=201)
def supplement(id:int,data:SupplementInput,response:Response,db=Depends(get_db),u=Depends(can_write)):
    parent=db.get(Dataset,id)
    d,duplicate=datasets.supplement(db,id,data)
    if duplicate:
        response.status_code=200
        record(db,u.email,'dataset.supplement.replay',{'id':d.id,'parent':parent.id if parent else id})
    else:
        record(db,u.email,'dataset.supplement',{'id':d.id,'parent':id,'merge':d.merge_detail})
    db.commit(); return {**dataset_dict(d),'duplicate':duplicate}
@router.get('/{id}')
def detail(id:int,db=Depends(get_db),u=Depends(current_user)):
    d=db.get(Dataset,id)
    if not d:raise HTTPException(404,'数据批次不存在')
    payload={**dataset_dict(d),'records':d.records}
    if d.parent_id:
        parent=db.get(Dataset,d.parent_id)
        payload['parent']=dataset_dict(parent) if parent else None
        payload['merge_detail']=d.merge_detail or {}
    payload['supplements']=[dataset_dict(x) for x in db.scalars(select(Dataset).where(Dataset.parent_id==d.id).order_by(Dataset.id))]
    return payload
