#!/usr/bin/env python3
"""Profile one GPU job using the same staging, lease, worker, and checks as live execution."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import uuid
from dataclasses import asdict
from pathlib import Path

from scheduling.features import extract_features
from scheduling.live import busy_gpus, lease
from scheduling.live_store import atomic_json, positive, snapshot_input
from scheduling.live_worker import run


def gpu_query(gpu_index: int, field: str) -> str:
    command = [
        "nvidia-smi",
        f"--id={gpu_index}",
        f"--query-gpu={field}",
        "--format=csv,noheader,nounits",
    ]
    return subprocess.run(
        command, check=True, capture_output=True, text=True, timeout=10
    ).stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--owner-id", default="experiment")
    parser.add_argument("--biological-group-id", default="")
    parser.add_argument("--split", choices=("train", "calibration", "test"), default="")
    parser.add_argument("--benchmark-sha256", default="")
    parser.add_argument("--gpu-index", type=int, default=0)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--cache", default="/workspace/cache")
    parser.add_argument("--msa-depth", type=int)
    parser.add_argument("--recycling-steps", type=int, default=3)
    parser.add_argument("--sampling-steps", type=int, default=200)
    parser.add_argument("--diffusion-samples", type=int, default=1)
    parser.add_argument("--sample-interval", type=float, default=0.5)
    parser.add_argument("--timeout-seconds", type=float, default=3600)
    parser.add_argument("--lock-dir", type=Path, default=Path(os.environ.get(
        "HELIXFLOW_LOCK_DIR", f"/tmp/helixflow-gpu-locks-{os.getuid()}"
    )))
    args = parser.parse_args()

    options = {
        "recycling_steps": args.recycling_steps,
        "sampling_steps": args.sampling_steps,
        "diffusion_samples": args.diffusion_samples,
    }
    if any(v <= 0 for v in options.values()) or args.repeat < 1:
        raise ValueError("inference options and repeat must be positive")
    if args.output.exists() or args.out_dir.exists():
        raise ValueError("use fresh output and out-dir paths for every profiling attempt")
    interval = positive(args.sample_interval, "sample_interval")
    timeout = positive(args.timeout_seconds, "timeout_seconds")
    features = extract_features(
        args.input, options=options, msa_depth_override=args.msa_depth, cache=Path(args.cache)
    )
    gpu_id = gpu_query(args.gpu_index, "uuid")
    if gpu_id in busy_gpus():
        raise RuntimeError("GPU already has a compute process; do not profile concurrently")
    fd = lease(args.lock_dir / f"{gpu_id}.lock")
    if fd is None:
        raise RuntimeError("GPU is leased by another worker")
    entered_worker = False
    try:
        folder = args.out_dir.resolve()
        folder.mkdir(parents=True, exist_ok=False)
        staged, hashes = snapshot_input(args.input.resolve(), folder / "inputs")
        request = {
            "attempt_id": uuid.uuid4().hex, "job_id": args.job_id, "ordinal": args.repeat,
            "backend": "boltz", "gpu_id": gpu_id, "cache": str(Path(args.cache).resolve()),
            "sample_interval": interval,
            "spec": {"input": str(staged), "input_hashes": hashes, "options": options,
                     "timeout_seconds": timeout},
        }
        atomic_json(folder / "request.json", request)
        entered_worker = True
        run(folder / "request.json", fd)
    finally:
        if not entered_worker:
            os.close(fd)
    receipt = json.loads((folder / "receipt.json").read_text())
    record = {
        "inference_seed": 42,
        "biological_group_id": args.biological_group_id, "split": args.split,
        "benchmark_sha256": args.benchmark_sha256,
        "hardware": gpu_query(args.gpu_index, "name"),
        "schema_version": "1.0", "evidence_type": "live_boltz_execution",
        "job_id": args.job_id,
        "owner_id": args.owner_id,
        "repeat": args.repeat,
        "input": str(staged), "input_hashes": hashes,
        "started_at_epoch": receipt["started_at"],
        "actual_runtime_seconds": receipt["runtime_seconds"],
        "actual_peak_memory_gib": receipt["peak_device_memory_gib"],
        "peak_incremental_memory_gib": receipt["peak_incremental_memory_gib"],
        "return_code": receipt["return_code"],
        "status": receipt["status"],
        "gpu_index": args.gpu_index, "gpu_id": gpu_id,
        "gpu_name": gpu_query(args.gpu_index, "name"),
        "driver_version": gpu_query(args.gpu_index, "driver_version"),
        "features": asdict(features),
        "command": receipt.get("command"),
        "receipt": str(folder / "receipt.json"), "reason": receipt["reason"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.output, record)
    if receipt["status"] != "SUCCEEDED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
