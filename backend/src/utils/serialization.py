import hashlib, json
def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
def dataset_dict(d):
    return {'id':d.id, 'name':d.name, 'source':d.source, 'rows':len(d.records), 'checksum':d.checksum, 'created_at':d.created_at}
def job_dict(j):
    return {k:getattr(j,k) for k in ['id','name','dataset_id','params','status','result','error','approved','created_at','finished_at']}
def report_dict(r):
    return {k:getattr(r,k) for k in ['id','name','job_id','destination','interval_seconds','next_run','enabled']}
def delivery_dict(d):
    return {k:getattr(d,k) for k in ['id','report_id','created_at','checksum','filename','destination']}
def retest_batch_dict(b):
    return {'id':b.id,'name':b.name,'source':b.source,'rows':len(b.records),'checksum':b.checksum,
            'occupied':b.occupied_by is not None,'occupied_by':b.occupied_by,'created_at':b.created_at}
def retest_voucher_dict(v):
    return {'id':v.id,'origin_job_id':v.origin_job_id,'retest_batch_id':v.retest_batch_id,
            'request_key':v.request_key,'status':v.status,'params':v.params,
            'origin_result':v.origin_result,'retest_result':v.retest_result,
            'direction':v.direction,'overlap':v.overlap,'filename':v.filename,
            'checksum':v.checksum,'created_at':v.created_at,'issued_at':v.issued_at,'attempts':v.attempts}
