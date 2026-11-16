from __future__ import annotations

import hashlib
import os
from typing import Any

import boto3

from shared.models import AttemptManifest, JobStatus, ResultManifest, utc_now

s3=boto3.client("s3"); table=boto3.resource("dynamodb").Table(os.environ["JOBS_TABLE"]); BUCKET=os.environ["ARTIFACT_BUCKET"]
def digest(key: str) -> str:
    body=s3.get_object(Bucket=BUCKET,Key=key)["Body"]; h=hashlib.sha256()
    for chunk in iter(lambda:body.read(8*1024*1024),b""): h.update(chunk)
    return h.hexdigest()
def handler(event: dict[str,Any], _context: Any) -> dict[str,str]:
    job_id=event["job_id"]; owner=event["owner_id"]; attempt=int(event.get("attempt",1)); source_key=event.get("attempt_manifest_key",f"jobs/{owner}/{job_id}/attempts/{attempt}/attempt-manifest.json")
    source=AttemptManifest.model_validate_json(s3.get_object(Bucket=BUCKET,Key=source_key)["Body"].read())
    if source.job_id != job_id or source.attempt != attempt: raise ValueError("attempt identity mismatch")
    for asset in source.assets:
        if s3.head_object(Bucket=BUCKET,Key=asset.key)["ContentLength"] != asset.size or digest(asset.key) != asset.sha256: raise ValueError(f"invalid asset: {asset.key}")
    result=ResultManifest(job_id=job_id,attempt=attempt,model_name=source.model_name,model_version=source.model_version,completed_at=utc_now(),assets=source.assets,provenance=source.provenance)
    key=f"jobs/{owner}/{job_id}/results/result-manifest.json"
    s3.put_object(Bucket=BUCKET,Key=key,Body=result.model_dump_json().encode(),ContentType="application/json",ServerSideEncryption="AES256")
    table.update_item(Key={"job_id":job_id},UpdateExpression="SET #s=:s,updated_at=:u,result_manifest_key=:k,attempt=:a REMOVE error_code,error_message",ExpressionAttributeNames={"#s":"status"},ExpressionAttributeValues={":s":JobStatus.SUCCEEDED.value,":u":utc_now(),":k":key,":a":attempt})
    return {"job_id":job_id,"result_manifest_key":key}
