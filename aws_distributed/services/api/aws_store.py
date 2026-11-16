from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from shared.models import (
    JobManifest,
    JobRecord,
    JobStatus,
    QueueMessage,
    ResultManifest,
    utc_now,
)

from .config import Settings


@dataclass
class AwsStore:
    settings: Settings

    def __post_init__(self) -> None:
        session = boto3.Session(region_name=self.settings.aws_region)
        self.s3 = session.client("s3")
        self.sqs = session.client("sqs")
        self.sfn = session.client("stepfunctions")
        self.table = session.resource("dynamodb").Table(self.settings.jobs_table)

    def create_draft(self, record: JobRecord) -> None:
        self.table.put_item(
            Item=record.model_dump(mode="json"),
            ConditionExpression="attribute_not_exists(job_id)",
        )

    def get_job(self, job_id: str) -> JobRecord | None:
        result = self.table.get_item(Key={"job_id": job_id}, ConsistentRead=True)
        item = result.get("Item")
        return JobRecord.model_validate(item) if item else None

    def list_jobs(self, owner_id: str, limit: int = 50) -> list[JobRecord]:
        result = self.table.query(
            IndexName=self.settings.jobs_owner_index,
            KeyConditionExpression=Key("owner_id").eq(owner_id),
            ScanIndexForward=False,
            Limit=limit,
        )
        return [JobRecord.model_validate(item) for item in result.get("Items", [])]

    def presign_upload(self, key: str, content_type: str) -> str:
        return self.s3.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.settings.artifact_bucket,
                "Key": key,
                "ContentType": content_type,
                "ServerSideEncryption": "AES256",
            },
            ExpiresIn=self.settings.upload_expiry_seconds,
        )

    def assert_object_exists(self, key: str) -> None:
        try:
            self.s3.head_object(Bucket=self.settings.artifact_bucket, Key=key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] in {"404", "NoSuchKey", "NotFound"}:
                raise FileNotFoundError(key) from exc
            raise

    def upload_json(self, key: str, value: dict[str, Any]) -> None:
        self.s3.put_object(
            Bucket=self.settings.artifact_bucket,
            Key=key,
            Body=json.dumps(value, separators=(",", ":")).encode(),
            ContentType="application/json",
            ServerSideEncryption="AES256",
        )

    def load_result_manifest(self, key: str) -> ResultManifest:
        response = self.s3.get_object(Bucket=self.settings.artifact_bucket, Key=key)
        return ResultManifest.model_validate_json(response["Body"].read())

    def presign_asset(self, key: str, filename: str) -> str:
        return self.s3.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.settings.artifact_bucket,
                "Key": key,
                "ResponseContentDisposition": f'inline; filename="{filename}"',
            },
            ExpiresIn=self.settings.asset_expiry_seconds,
        )

    def submit(self, current: JobRecord, manifest: JobManifest, idempotency_key: str) -> None:
        manifest_key = f"jobs/{current.owner_id}/{current.job_id}/input/manifest.json"
        self.upload_json(manifest_key, manifest.model_dump(mode="json"))
        timestamp = utc_now()
        try:
            self.table.update_item(
                Key={"job_id": current.job_id},
                UpdateExpression=(
                    "SET #status = :queued, updated_at = :updated, input_key = :input, "
                    "idempotency_key = :token, manifest_key = :manifest"
                ),
                ConditionExpression=(
                    "#status = :draft AND "
                    "(attribute_not_exists(idempotency_key) OR idempotency_key = :token)"
                ),
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":queued": JobStatus.QUEUED.value,
                    ":draft": JobStatus.DRAFT.value,
                    ":updated": timestamp,
                    ":input": manifest.input_key,
                    ":token": idempotency_key,
                    ":manifest": manifest_key,
                },
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                existing = self.get_job(current.job_id)
                if not existing or existing.idempotency_key != idempotency_key:
                    raise ValueError("job was already submitted") from exc
                return
            raise

        message = QueueMessage(
            job_id=current.job_id,
            owner_id=current.owner_id,
            manifest_key=manifest_key,
            submitted_at=timestamp,
        )
        self.sqs.send_message(
            QueueUrl=self.settings.submission_queue_url,
            MessageBody=message.model_dump_json(),
        )

    def cancel(self, job: JobRecord) -> None:
        if job.status in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}:
            return
        if job.workflow_arn:
            self.sfn.stop_execution(
                executionArn=job.workflow_arn,
                error="UserCancelled",
                cause=f"Cancelled job {job.job_id}",
            )
        for batch_job_id in job.batch_job_ids:
            boto3.client("batch", region_name=self.settings.aws_region).terminate_job(
                jobId=batch_job_id,
                reason="User cancelled job",
            )
        self.table.update_item(
            Key={"job_id": job.job_id},
            UpdateExpression="SET #status = :status, updated_at = :updated",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": JobStatus.CANCELLED.value,
                ":updated": utc_now(),
            },
        )

