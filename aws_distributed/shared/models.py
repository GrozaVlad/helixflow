from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class JobStatus(StrEnum):
    DRAFT = "DRAFT"
    UPLOADED = "UPLOADED"
    QUEUED = "QUEUED"
    PREPARING = "PREPARING"
    GPU_QUEUED = "GPU_QUEUED"
    RUNNING = "RUNNING"
    FINALIZING = "FINALIZING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL_STATES = {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}


class PredictionOptions(BaseModel):
    use_msa: bool = True
    use_potentials: bool = False
    recycling_steps: int = Field(default=3, ge=1, le=10)
    sampling_steps: int = Field(default=200, ge=20, le=500)
    diffusion_samples: int = Field(default=1, ge=1, le=5)


class UploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=180)
    content_type: str = "application/octet-stream"

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        if "/" in value or "\\" in value or value.startswith("."):
            raise ValueError("filename must be a plain basename")
        if not value.lower().endswith((".yaml", ".yml", ".fasta", ".fa")):
            raise ValueError("only YAML and FASTA inputs are supported")
        return value


class UploadResponse(BaseModel):
    job_id: str
    input_key: str
    upload_url: str
    expires_in: int


class SubmitJobRequest(BaseModel):
    job_id: str
    input_key: str
    idempotency_key: str = Field(min_length=8, max_length=128)
    model_name: str = "boltz-2"
    options: PredictionOptions = Field(default_factory=PredictionOptions)
    msa_keys: list[str] = Field(default_factory=list)


class JobManifest(BaseModel):
    schema_version: str = "1.0"
    job_id: str
    owner_id: str
    model_name: str
    input_key: str
    msa_keys: list[str] = Field(default_factory=list)
    options: PredictionOptions
    created_at: str
    code_version: str
    model_version: str


class JobRecord(BaseModel):
    job_id: str
    owner_id: str
    status: JobStatus
    created_at: str
    updated_at: str
    input_key: str | None = None
    manifest_key: str | None = None
    idempotency_key: str | None = None
    result_manifest_key: str | None = None
    workflow_arn: str | None = None
    batch_job_ids: list[str] = Field(default_factory=list)
    attempt: int = 0
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResultAsset(BaseModel):
    key: str
    name: str
    size: int
    sha256: str
    media_type: str


class ResultManifest(BaseModel):
    schema_version: str = "1.0"
    job_id: str
    attempt: int
    model_name: str
    model_version: str
    completed_at: str
    assets: list[ResultAsset]
    provenance: dict[str, str]


class AttemptManifest(BaseModel):
    schema_version: str = "1.0"
    job_id: str
    attempt: int
    model_name: str
    model_version: str
    assets: list[ResultAsset]
    provenance: dict[str, str]


class QueueMessage(BaseModel):
    schema_version: str = "1.0"
    job_id: str
    owner_id: str
    manifest_key: str
    submitted_at: str


def utc_now() -> str:
    return datetime.now(UTC).isoformat()

