"""独立复测：候选试算、凭证签发、日表原子占用与幂等恢复。

防伪要点：
- 复测沿用原分析权重参数，只对照两队加权差值方向，不重新选口径；
- 按 (日, 队, 区域) 辨认观察，与原分析批次撞上的日表不能参评；
- 同一原分析只允许一张凭证（待签或已签），签发时其复测日表一次性占用；
- request_key 幂等：中断后重试同次签发不重复占用、不重复生成简报。
"""
import csv
import hashlib
import io
import json
import math
import os
import time

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from redis import Redis

from src.config.settings import REDIS_URL, ARTIFACT_DIR
from src.models import Dataset, Job, RetestBatch, RetestVoucher
from src.services.business import (
    analyze,
    direction_of,
    metadata,
    observation_keys,
    weighted_delta,
)
from src.utils.serialization import checksum


# ---------------- 候选日表批次 ----------------

def create_batch(db, data, user):
    name = data.name.strip()
    if len(name) < 2:
        raise HTTPException(422, '批次名称去除空格后至少需要两个字符')
    if db.scalar(select(RetestBatch).where(RetestBatch.name == name)):
        raise HTTPException(409, '该复测日表名称已存在，请修改名称')
    columns = metadata()['columns']
    for index, row in enumerate(data.records):
        for c in columns:
            value = row.get(c['key'])
            if value is None or value == '':
                raise HTTPException(422, f'第 {index + 1} 行缺少字段 {c["label"]}')
            if c['type'] == 'number':
                try:
                    if isinstance(value, bool) or not math.isfinite(float(value)):
                        raise ValueError()
                    row[c['key']] = float(value)
                except (TypeError, ValueError, OverflowError):
                    raise HTTPException(422, f'第 {index + 1} 行 {c["label"]} 必须为有限数值')
    # 与正式分析同一份服务端校验（重复键、抽样框冲突、计数边界等），避免坏数据进入试算
    try:
        analyze(data.records, {p['key']: p['default'] for p in metadata()['parameters']})
    except ValueError as error:
        raise HTTPException(422, f'复测日表未通过校验：{error}') from None
    batch = RetestBatch(
        name=name, source=data.source, records=data.records,
        checksum=checksum(data.records), created_by=user.id, created_at=time.time(),
    )
    db.add(batch)
    db.flush()
    return batch


def _origin_job(db, origin_job_id):
    job = db.get(Job, origin_job_id)
    if not job:
        raise HTTPException(404, '原分析任务不存在')
    if job.status != 'completed' or not job.approved:
        raise HTTPException(409, '仅已完成且获批准的分析可以发起独立复测')
    return job


def _retest_batch(db, retest_batch_id, for_update=False):
    batch = db.get(RetestBatch, retest_batch_id, with_for_update=for_update)
    if not batch:
        raise HTTPException(404, '复测日表批次不存在')
    return batch


def _overlap(origin_records, retest_records):
    """按 日/队/区域 辨认观察，返回撞上的批次键。"""
    origin_keys = observation_keys(origin_records)
    shared = sorted(origin_keys & observation_keys(retest_records))
    return {
        'has_overlap': bool(shared),
        'matched_observations': [
            {'day': day, 'team': team, 'zone': zone} for day, team, zone in shared
        ],
        'origin_rows': len(origin_records),
        'retest_rows': len(retest_records),
    }


def _evaluate(db, job, batch):
    """沿用原权重试算并对照两队差值方向。不写库，可对任意重叠候选各自试算。"""
    dataset = db.get(Dataset, job.dataset_id)
    overlap = _overlap(dataset.records, batch.records)
    params = dict(job.params)  # 沿用原分析权重与最低观察量
    try:
        result = analyze(batch.records, params)
        origin_delta = weighted_delta(job.result)
        retest_delta = weighted_delta(result)
    except ValueError as error:
        raise HTTPException(422, f'复测日表无法按原权重计算：{error}') from None
    same_direction = (origin_delta > 0 and retest_delta > 0) \
        or (origin_delta < 0 and retest_delta < 0) \
        or (origin_delta == 0 and retest_delta == 0)
    direction = {
        'origin_weighted_delta': round(origin_delta, 3),
        'retest_weighted_delta': round(retest_delta, 3),
        'origin_direction': direction_of(origin_delta),
        'retest_direction': direction_of(retest_delta),
        'same_direction': same_direction,
    }
    return result, overlap, direction


def trial(db, data, user):
    """重叠候选可各自试算：只返回试算结论与重叠辨认，不占用日表。"""
    job = _origin_job(db, data.origin_job_id)
    batch = _retest_batch(db, data.retest_batch_id)
    result, overlap, direction = _evaluate(db, job, batch)
    occupied = batch.occupied_by is not None
    return {
        'origin_job_id': job.id,
        'retest_batch_id': batch.id,
        'eligible': (not overlap['has_overlap']) and not occupied,
        'occupied': occupied,
        'overlap': overlap,
        'direction': direction,
        'retest_summary': result.get('summary'),
        'retest_metrics': result.get('metrics'),
    }


# ---------------- 凭证签发（原子占用 + 幂等） ----------------

def _briefing_bytes(voucher, job, batch):
    """签发时的简报：附原分析与复测两份结论及批次指纹。"""
    out = io.StringIO()
    out.write('\ufeff')  # Excel 兼容的 UTF-8 BOM
    writer = csv.writer(out)
    writer.writerow(['独立复测凭证', f'V{voucher.id:06d}'])
    writer.writerow(['原分析', job.name])
    writer.writerow(['原分析批次', f'数据集#{job.dataset_id}'])
    writer.writerow(['复测日表批次', batch.name])
    writer.writerow(['复测批次校验指纹', batch.checksum])
    writer.writerow(['沿用权重参数', json.dumps(voucher.params, ensure_ascii=False)])
    d = voucher.direction
    writer.writerow(['原分析加权A−B(百分点)', d.get('origin_weighted_delta')])
    writer.writerow(['复测加权A−B(百分点)', d.get('retest_weighted_delta')])
    writer.writerow(['原分析差值方向', d.get('origin_direction')])
    writer.writerow(['复测差值方向', d.get('retest_direction')])
    writer.writerow(['方向是否一致', '一致' if d.get('same_direction') else '不一致'])
    writer.writerow([])
    writer.writerow(['== 原分析结论 =='])
    writer.writerow([job.result.get('summary', '')])
    writer.writerow([])
    writer.writerow(['== 复测结论 =='])
    writer.writerow([voucher.retest_result.get('summary', '')])
    writer.writerow([])
    writer.writerow(['== 复测批次明细（日/队/区域/合格/观察） =='])
    writer.writerow(['观察日', '采样队', '区域层', '合格数', '观察点数', '抽样框规模'])
    for row in batch.records:
        writer.writerow([row.get('day'), row.get('team'), row.get('zone'),
                         row.get('passed'), row.get('observed'), row.get('frame_size')])
    return out.getvalue().encode('utf-8')


def _issue_lock_key(origin_job_id):
    return f'retest:issue:job:{origin_job_id}'


def issue(db, data, user):
    """签发复测凭证。同一 request_key 重试返回同一凭证（中断恢复，不重复占用）。"""
    # Redis 进程锁先挡住同原分析的并发签发；数据库唯一约束与行锁为最终兜底
    redis = Redis.from_url(REDIS_URL, socket_timeout=3)
    lock_key = _issue_lock_key(data.origin_job_id)
    got_lock = False
    try:
        try:
            got_lock = bool(redis.set(lock_key, '1', nx=True, ex=30))
        except Exception:
            got_lock = True  # Redis 不可用时依赖数据库约束兜底
        if not got_lock:
            raise HTTPException(409, '同一原分析正在签发，请稍后在待签列表查看结果')
        return _issue_tx(db, data, user)
    finally:
        if got_lock:
            try:
                redis.delete(lock_key)
            except Exception:
                pass
            redis.close()


def _issue_tx(db, data, user):
    # 1. 幂等恢复：同一 request_key 直接返回既有凭证（待签或已签）
    existing = db.scalar(select(RetestVoucher).where(RetestVoucher.request_key == data.request_key))
    if existing:
        return existing

    job = _origin_job(db, data.origin_job_id)

    # 2. 同一原分析只允许一张凭证（UniqueConstraint 兜底并发）
    twin = db.scalar(select(RetestVoucher).where(RetestVoucher.origin_job_id == job.id))
    if twin:
        state = '已签' if twin.status == 'issued' else '待签'
        raise HTTPException(409, f'该原分析已有{state}复测凭证，不能重复签发')

    # 3. 行锁锁定复测日表，保证占用与凭证一并生效
    batch = _retest_batch(db, data.retest_batch_id, for_update=True)
    if batch.occupied_by is not None:
        raise HTTPException(409, '该复测日表已被其他凭证占用，不能重复参评')

    result, overlap, direction = _evaluate(db, job, batch)
    if overlap['has_overlap']:
        matched = '、'.join(
            f"{x['day']}/{x['team']}/{x['zone']}" for x in overlap['matched_observations'][:5]
        )
        raise HTTPException(409, f'复测日表与原分析批次存在重叠观察（{matched}），不能参评')

    voucher = RetestVoucher(
        origin_job_id=job.id,
        retest_batch_id=batch.id,
        request_key=data.request_key,
        status='pending',
        params=dict(job.params),
        origin_result=job.result,
        retest_result=result,
        direction=direction,
        overlap=overlap,
        created_by=user.id,
        created_at=time.time(),
        attempts=1,
    )
    db.add(voucher)
    try:
        db.flush()  # 先取得凭证 id，占用才能指向它
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, '同一原分析的复测凭证已存在，或请求编号重复') from None

    # 4. 日表占用与凭证一并生效；后续失败整体回滚，不会留下无主占用
    batch.occupied_by = voucher.id

    # 5. 生成签发简报（两份结论 + 批次），失败则整体回滚，重试不产生重复文件
    payload = _briefing_bytes(voucher, job, batch)
    voucher.filename = f'retest-voucher-{voucher.id}.csv'
    voucher.checksum = hashlib.sha256(payload).hexdigest()
    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    with open(os.path.join(ARTIFACT_DIR, voucher.filename), 'wb') as f:
        f.write(payload)
    with open(os.path.join(ARTIFACT_DIR, voucher.filename + '.json'), 'w') as f:
        json.dump({
            'voucher_id': voucher.id,
            'request_key': voucher.request_key,
            'origin_job': job.name,
            'retest_batch': batch.name,
            'params': voucher.params,
            'origin_result': voucher.origin_result,
            'retest_result': voucher.retest_result,
            'direction': voucher.direction,
            'overlap': voucher.overlap,
            'checksum': voucher.checksum,
        }, f, ensure_ascii=False, allow_nan=False)

    voucher.status = 'issued'
    voucher.issued_at = time.time()
    db.commit()
    return voucher


def list_vouchers(db, status=None):
    stmt = select(RetestVoucher).order_by(RetestVoucher.id.desc())
    if status in ('pending', 'issued'):
        stmt = stmt.where(RetestVoucher.status == status)
    return list(db.scalars(stmt))


def list_batches(db):
    return list(db.scalars(select(RetestBatch).order_by(RetestBatch.id.desc())))


def recover_pending(db):
    """中断恢复：同次签发在写简报前崩溃会留下 pending 凭证。

    日表占用与凭证在同一事务内提交，故 pending 凭证的占用已经生效；
    恢复时沿用同一 request_key 补齐简报并转已签，不新建凭证、不二次占用。
    无法补齐（日表/原分析被删、磁盘故障）的凭证保持 pending，可在待签列表查到。
    """
    recovered = []
    pending = list(db.scalars(select(RetestVoucher).where(RetestVoucher.status == 'pending')))
    for voucher in pending:
        voucher.attempts = (voucher.attempts or 0) + 1
        job = db.get(Job, voucher.origin_job_id)
        batch = db.get(RetestBatch, voucher.retest_batch_id)
        if not job or not batch:
            continue
        try:
            payload = _briefing_bytes(voucher, job, batch)
            voucher.filename = f'retest-voucher-{voucher.id}.csv'
            voucher.checksum = hashlib.sha256(payload).hexdigest()
            os.makedirs(ARTIFACT_DIR, exist_ok=True)
            with open(os.path.join(ARTIFACT_DIR, voucher.filename), 'wb') as f:
                f.write(payload)
            with open(os.path.join(ARTIFACT_DIR, voucher.filename + '.json'), 'w') as f:
                json.dump({
                    'voucher_id': voucher.id,
                    'request_key': voucher.request_key,
                    'origin_job': job.name,
                    'retest_batch': batch.name,
                    'params': voucher.params,
                    'origin_result': voucher.origin_result,
                    'retest_result': voucher.retest_result,
                    'direction': voucher.direction,
                    'overlap': voucher.overlap,
                    'checksum': voucher.checksum,
                }, f, ensure_ascii=False, allow_nan=False)
            voucher.status = 'issued'
            voucher.issued_at = time.time()
            recovered.append(voucher.id)
        except OSError:
            continue
    if recovered:
        db.commit()
    return recovered
