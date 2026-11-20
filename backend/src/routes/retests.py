import os
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from src.config.database import get_db
from src.config.settings import ARTIFACT_DIR
from src.models import RetestBatch, RetestVoucher
from src.schemas.retest import RetestBatchInput, RetestTrialInput, RetestIssueInput
from src.middlewares.auth import current_user, can_write, admin_only
from src.services import retests
from src.services.audit import record
from src.utils.serialization import retest_batch_dict, retest_voucher_dict

router = APIRouter(prefix='/retests')


@router.get('/batches')
def batches(db=Depends(get_db), u=Depends(current_user)):
    return [retest_batch_dict(b) for b in retests.list_batches(db)]


@router.post('/batches', status_code=201)
def create_batch(data: RetestBatchInput, db=Depends(get_db), u=Depends(can_write)):
    b = retests.create_batch(db, data, u)
    record(db, u.email, 'retest.batch.create', {'id': b.id, 'rows': len(b.records)})
    db.commit()
    return retest_batch_dict(b)


@router.post('/trial')
def trial(data: RetestTrialInput, db=Depends(get_db), u=Depends(can_write)):
    return retests.trial(db, data, u)


@router.post('/issue', status_code=201)
def issue(data: RetestIssueInput, db=Depends(get_db), u=Depends(admin_only)):
    v = retests.issue(db, data, u)
    record(db, u.email, 'retest.issue', {
        'id': v.id, 'origin_job_id': v.origin_job_id,
        'retest_batch_id': v.retest_batch_id, 'request_key': v.request_key, 'status': v.status,
    })
    db.commit()  # 凭证已在服务内提交，这里补提审计轨迹
    return retest_voucher_dict(v)


@router.get('/vouchers')
def vouchers(status: str | None = None, db=Depends(get_db), u=Depends(current_user)):
    return [retest_voucher_dict(v) for v in retests.list_vouchers(db, status)]


@router.get('/vouchers/{id}')
def voucher_detail(id: int, db=Depends(get_db), u=Depends(current_user)):
    v = db.get(RetestVoucher, id)
    if not v:
        raise HTTPException(404, '复测凭证不存在')
    return retest_voucher_dict(v)


@router.get('/vouchers/{id}/download')
def download(id: int, format: str = 'csv', db=Depends(get_db), u=Depends(current_user)):
    v = db.get(RetestVoucher, id)
    if not v:
        raise HTTPException(404, '复测凭证不存在')
    if v.status != 'issued' or not v.filename:
        raise HTTPException(409, '凭证尚未签发完成，暂无简报可下载')
    if format not in ('csv', 'json'):
        raise HTTPException(422, '支持 CSV 或 JSON')
    filename = v.filename + ('.json' if format == 'json' else '')
    path = os.path.join(ARTIFACT_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(404, '简报文件不存在，系统将在恢复后补齐')
    return FileResponse(
        path, filename=filename,
        media_type='application/json' if format == 'json' else 'text/csv; charset=utf-8',
    )
