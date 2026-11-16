from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import torch
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path("/workspace")
INPUTS = ROOT / "data/inputs"
OUTPUTS = ROOT / "data/outputs"
STATIC = ROOT / "app/static"
ALLOWED_SUFFIXES = {".yaml", ".yml", ".fasta", ".fa"}
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
GPU_LOCK = threading.Lock()

INPUTS.mkdir(parents=True, exist_ok=True)
OUTPUTS.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Local Boltz-2", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_name(name: str) -> str:
    base = Path(name).name
    clean = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    return clean[:180] or "input.yaml"


def update_job(job_id: str, **values: object) -> None:
    with JOBS_LOCK:
        JOBS[job_id].update(values)


def run_prediction(job_id: str, input_path: Path, options: dict) -> None:
    output_dir = OUTPUTS / job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "run.log"
    command = [
        "boltz", "predict", str(input_path),
        "--out_dir", str(output_dir),
        "--cache", os.environ.get("BOLTZ_CACHE", "/workspace/cache"),
        "--devices", "1",
        "--accelerator", "gpu",
        "--recycling_steps", str(options["recycling_steps"]),
        "--sampling_steps", str(options["sampling_steps"]),
        "--diffusion_samples", str(options["diffusion_samples"]),
        "--max_parallel_samples", "1",
        "--num_workers", "0",
        "--preprocessing-threads", "4",
    ]
    if options["use_msa_server"]:
        command.append("--use_msa_server")
    if options["use_potentials"]:
        command.append("--use_potentials")
    if options["override"]:
        command.append("--override")

    update_job(job_id, status="queued", command=command, output_dir=str(output_dir))
    try:
        with GPU_LOCK:
            update_job(job_id, status="running", started_at=now())
            with log_path.open("w", encoding="utf-8") as log:
                process = subprocess.Popen(
                    command,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                update_job(job_id, pid=process.pid)
                return_code = process.wait()
        files = [
            str(path.relative_to(output_dir))
            for path in output_dir.rglob("*")
            if path.is_file() and path.name != "run.log"
        ]
        structure_files = [
            path for path in files
            if Path(path).suffix.lower() in {".cif", ".pdb"}
        ]
        completed = return_code == 0 and bool(structure_files)
        error = None
        if return_code == 0 and not structure_files:
            error = (
                "Boltz exited without producing a structure. "
                "The input may have been skipped; inspect the run log."
            )
        update_job(
            job_id,
            status="completed" if completed else "failed",
            return_code=return_code,
            files=sorted(files),
            error=error,
            finished_at=now(),
        )
    except Exception as exc:
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"\nLauncher error: {exc}\n")
        update_job(job_id, status="failed", error=str(exc), finished_at=now())


def restore_jobs() -> None:
    """Restore persisted jobs after the local container restarts."""
    for output_dir in OUTPUTS.iterdir():
        if not output_dir.is_dir():
            continue
        job_id = output_dir.name
        input_dir = INPUTS / job_id
        inputs = sorted(path for path in input_dir.iterdir() if path.is_file()) if input_dir.is_dir() else []
        files = sorted(
            str(path.relative_to(output_dir))
            for path in output_dir.rglob("*")
            if path.is_file() and path.name != "run.log"
        )
        structures = [path for path in files if Path(path).suffix.lower() in {".cif", ".pdb"}]
        timestamp_source = inputs[0] if inputs else output_dir
        JOBS[job_id] = {
            "id": job_id,
            "filename": inputs[0].name if inputs else "unknown input",
            "status": "completed" if structures else "failed",
            "created_at": datetime.fromtimestamp(
                timestamp_source.stat().st_mtime, timezone.utc
            ).isoformat(),
            "options": {},
            "files": files,
            "restored": True,
        }


restore_jobs()


@app.get("/", response_class=HTMLResponse)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "cuda_available": torch.cuda.is_available(),
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "boltz_cache": os.environ.get("BOLTZ_CACHE"),
    }


@app.get("/api/jobs")
def list_jobs() -> list[dict]:
    with JOBS_LOCK:
        return sorted(JOBS.values(), key=lambda item: item["created_at"], reverse=True)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    with JOBS_LOCK:
        if job_id not in JOBS:
            raise HTTPException(404, "Job not found")
        return JOBS[job_id]


@app.get("/api/jobs/{job_id}/log", response_class=PlainTextResponse)
def get_log(job_id: str) -> str:
    log_path = OUTPUTS / job_id / "run.log"
    if not log_path.exists():
        return "Waiting for the worker..."
    return log_path.read_text(encoding="utf-8", errors="replace")[-100_000:]


@app.get("/api/jobs/{job_id}/files/{file_path:path}")
def get_result(job_id: str, file_path: str) -> FileResponse:
    root = (OUTPUTS / job_id).resolve()
    target = (root / file_path).resolve()
    if root not in target.parents or not target.is_file():
        raise HTTPException(404, "Result file not found")
    return FileResponse(target, filename=target.name)


@app.post("/api/jobs", status_code=202)
async def create_job(
    file: Annotated[UploadFile, File()],
    use_msa_server: Annotated[bool, Form()] = True,
    use_potentials: Annotated[bool, Form()] = False,
    override: Annotated[bool, Form()] = False,
    recycling_steps: Annotated[int, Form(ge=1, le=10)] = 3,
    sampling_steps: Annotated[int, Form(ge=20, le=500)] = 200,
    diffusion_samples: Annotated[int, Form(ge=1, le=5)] = 1,
) -> dict:
    filename = safe_name(file.filename or "input.yaml")
    if Path(filename).suffix.lower() not in ALLOWED_SUFFIXES:
        raise HTTPException(400, "Upload a YAML or FASTA input")
    content = await file.read()
    if not content or len(content) > 10 * 1024 * 1024:
        raise HTTPException(400, "Input must be between 1 byte and 10 MB")

    job_id = uuid.uuid4().hex[:12]
    job_input_dir = INPUTS / job_id
    job_input_dir.mkdir(parents=True)
    input_path = job_input_dir / filename
    input_path.write_bytes(content)
    options = {
        "use_msa_server": use_msa_server,
        "use_potentials": use_potentials,
        "override": override,
        "recycling_steps": recycling_steps,
        "sampling_steps": sampling_steps,
        "diffusion_samples": diffusion_samples,
    }
    job = {
        "id": job_id,
        "filename": filename,
        "status": "queued",
        "created_at": now(),
        "options": options,
        "files": [],
    }
    with JOBS_LOCK:
        JOBS[job_id] = job
    threading.Thread(
        target=run_prediction,
        args=(job_id, input_path, options),
        daemon=True,
    ).start()
    return job

