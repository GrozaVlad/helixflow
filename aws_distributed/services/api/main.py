from __future__ import annotations

import uuid
from functools import lru_cache
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from shared.models import (
    JobManifest,
    JobRecord,
    JobStatus,
    SubmitJobRequest,
    UploadRequest,
    UploadResponse,
    utc_now,
)

from .aws_store import AwsStore
from .config import Settings, get_settings

app = FastAPI(title="Distributed Boltz Workflow API", version="0.1.0")


@lru_cache
def store() -> AwsStore:
    return AwsStore(get_settings())


def current_owner(
    request: Request,
    settings: Settings = Depends(get_settings),
    research_user: str | None = Header(default=None, alias="X-Researcher-Id"),
) -> str:
    owner = request.headers.get("x-amzn-oidc-identity")
    if not owner and settings.auth_disabled:
        owner = research_user or "local-researcher"
    if not owner:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required")
    return owner


def owned_job(job_id: str, owner: str, aws: AwsStore) -> JobRecord:
    job = aws.get_job(job_id)
    if not job or job.owner_id != owner:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return job


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "boltz-control-plane"}


@app.post("/api/uploads", response_model=UploadResponse, status_code=201)
def create_upload(
    body: UploadRequest,
    owner: str = Depends(current_owner),
    aws: AwsStore = Depends(store),
) -> UploadResponse:
    job_id = uuid.uuid4().hex
    timestamp = utc_now()
    input_key = f"jobs/{owner}/{job_id}/input/{body.filename}"
    aws.create_draft(
        JobRecord(
            job_id=job_id,
            owner_id=owner,
            status=JobStatus.DRAFT,
            created_at=timestamp,
            updated_at=timestamp,
            input_key=input_key,
        )
    )
    return UploadResponse(
        job_id=job_id,
        input_key=input_key,
        upload_url=aws.presign_upload(input_key, body.content_type),
        expires_in=aws.settings.upload_expiry_seconds,
    )


@app.post("/api/jobs", status_code=202)
def submit_job(
    body: SubmitJobRequest,
    owner: str = Depends(current_owner),
    aws: AwsStore = Depends(store),
) -> JobRecord:
    job = owned_job(body.job_id, owner, aws)
    if body.input_key != job.input_key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "input key does not match draft")
    try:
        aws.assert_object_exists(body.input_key)
        for key in body.msa_keys:
            aws.assert_object_exists(key)
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, f"missing uploaded object: {exc}") from exc

    manifest = JobManifest(
        job_id=job.job_id,
        owner_id=owner,
        model_name=body.model_name,
        input_key=body.input_key,
        msa_keys=body.msa_keys,
        options=body.options,
        created_at=job.created_at,
        code_version=aws.settings.code_version,
        model_version=aws.settings.model_version,
    )
    try:
        aws.submit(job, manifest, body.idempotency_key)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return aws.get_job(job.job_id) or job


@app.get("/api/jobs", response_model=list[JobRecord])
def list_jobs(
    owner: str = Depends(current_owner),
    aws: AwsStore = Depends(store),
) -> list[JobRecord]:
    return aws.list_jobs(owner)


@app.get("/api/jobs/{job_id}", response_model=JobRecord)
def get_job(
    job_id: str,
    owner: str = Depends(current_owner),
    aws: AwsStore = Depends(store),
) -> JobRecord:
    return owned_job(job_id, owner, aws)


@app.post("/api/jobs/{job_id}/cancel", response_model=JobRecord)
def cancel_job(
    job_id: str,
    owner: str = Depends(current_owner),
    aws: AwsStore = Depends(store),
) -> JobRecord:
    job = owned_job(job_id, owner, aws)
    aws.cancel(job)
    return aws.get_job(job_id) or job


@app.get("/api/jobs/{job_id}/assets")
def list_assets(
    job_id: str,
    owner: str = Depends(current_owner),
    aws: AwsStore = Depends(store),
) -> dict:
    job = owned_job(job_id, owner, aws)
    if job.status != JobStatus.SUCCEEDED or not job.result_manifest_key:
        raise HTTPException(status.HTTP_409_CONFLICT, "results are not available")
    manifest = aws.load_result_manifest(job.result_manifest_key)
    return {
        "job_id": job_id,
        "expires_in": aws.settings.asset_expiry_seconds,
        "assets": [
            {
                **asset.model_dump(),
                "url": aws.presign_asset(asset.key, asset.name),
            }
            for asset in manifest.assets
        ],
    }



UI_ROOT = Path(__file__).resolve().parents[2] / "ui"
if UI_ROOT.exists():
    app.mount("/ui", StaticFiles(directory=UI_ROOT), name="ui")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(UI_ROOT / "index.html")
