from __future__ import annotations

import os
from typing import Any

import boto3

from shared.models import JobStatus, utc_now

table=boto3.resource("dynamodb").Table(os.environ["JOBS_TABLE"])
STATUS={"SUBMITTED":JobStatus.GPU_QUEUED,"PENDING":JobStatus.GPU_QUEUED,"RUNNABLE":JobStatus.GPU_QUEUED,"STARTING":JobStatus.RUNNING,"RUNNING":JobStatus.RUNNING}

def handler(event: dict[str,Any], _context: Any) -> None:
    d=event.get("detail",{}); job_id=d.get("tags",{}).get("ResearchJobId"); status=STATUS.get(d.get("status"))
    if not job_id or not status: return
    expression="SET #s=:s, updated_at=:u"; values={":s":status.value,":u":utc_now()}
    if d.get("jobId"): expression+=" ADD batch_job_ids :ids"; values[":ids"]={d["jobId"]}
    table.update_item(Key={"job_id":job_id},UpdateExpression=expression,ExpressionAttributeNames={"#s":"status"},ExpressionAttributeValues=values)
