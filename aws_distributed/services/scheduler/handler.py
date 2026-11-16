from __future__ import annotations

import json
import os
from decimal import Decimal
from typing import Any

import boto3

from shared.models import JobStatus, utc_now
from shared.scheduling import decide

s3 = boto3.client("s3")
table = boto3.resource("dynamodb").Table(os.environ["JOBS_TABLE"])
BUCKET = os.environ["ARTIFACT_BUCKET"]


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    job_id = event["job_id"]
    owner_id = event["owner_id"]
    prepared_key = event.get(
        "prepared_manifest_key",
        f"jobs/{owner_id}/{job_id}/prepared/manifest.json",
    )
    response = s3.get_object(Bucket=BUCKET, Key=prepared_key)
    prepared_manifest = json.loads(response["Body"].read())
    decision = decide(owner_id, prepared_manifest)
    metadata = {
        "scheduling_policy": decision.policy,
        "share_identifier": decision.share_identifier,
        "scheduling_priority": decision.scheduling_priority,
    }
    if decision.prediction:
        metadata.update(
            {
                "runtime_p50_seconds": Decimal(
                    str(decision.prediction.runtime_p50_seconds)
                ),
                "runtime_p90_seconds": Decimal(
                    str(decision.prediction.runtime_p90_seconds)
                ),
                "memory_p90_gib": Decimal(str(decision.prediction.memory_p90_gib)),
                "predictor_version": decision.prediction.predictor_version,
            }
        )
    if decision.fallback_reason:
        metadata["fallback_reason"] = decision.fallback_reason
    table.update_item(
        Key={"job_id": job_id},
        UpdateExpression="SET #s=:s, updated_at=:u, scheduling=:m",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": JobStatus.GPU_QUEUED.value,
            ":u": utc_now(),
            ":m": metadata,
        },
    )
    return decision.model_dump(mode="json")
