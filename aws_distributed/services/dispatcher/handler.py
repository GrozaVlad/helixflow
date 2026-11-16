from __future__ import annotations

import hashlib
import json
import os
from typing import Any

import boto3
from botocore.exceptions import ClientError

from shared.models import JobStatus, QueueMessage, utc_now

sfn=boto3.client("stepfunctions")
table=boto3.resource("dynamodb").Table(os.environ["JOBS_TABLE"])
STATE_MACHINE_ARN=os.environ["STATE_MACHINE_ARN"]

def execution_name(job_id: str) -> str:
    return f"boltz-{job_id[:48]}-{hashlib.sha256(job_id.encode()).hexdigest()[:12]}"[:80]

def handler(event: dict[str,Any], _context: Any) -> dict[str,list[dict[str,str]]]:
    failures=[]
    for record in event.get("Records",[]):
        try:
            message=QueueMessage.model_validate_json(record["body"])
            try:
                response=sfn.start_execution(stateMachineArn=STATE_MACHINE_ARN,name=execution_name(message.job_id),input=json.dumps(message.model_dump(mode="json")))
                arn=response["executionArn"]
            except ClientError as exc:
                if exc.response["Error"]["Code"] != "ExecutionAlreadyExists": raise
                arn=f"{STATE_MACHINE_ARN.replace(':stateMachine:',':execution:')}:{execution_name(message.job_id)}"
            table.update_item(Key={"job_id":message.job_id},UpdateExpression="SET #s=:s, workflow_arn=:a, updated_at=:u",ConditionExpression="#s=:q OR workflow_arn=:a",ExpressionAttributeNames={"#s":"status"},ExpressionAttributeValues={":s":JobStatus.PREPARING.value,":q":JobStatus.QUEUED.value,":a":arn,":u":utc_now()})
        except Exception:  # noqa: BLE001 -- isolate malformed SQS deliveries
            failures.append({"itemIdentifier":record["messageId"]})
    return {"batchItemFailures":failures}
