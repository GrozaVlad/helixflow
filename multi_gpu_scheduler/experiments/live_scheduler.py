"""CLI for durable single-host Boltz campaigns and measured-result exports."""

from __future__ import annotations

import argparse
import csv
import importlib.metadata
import json
import os
import platform
import statistics
import subprocess
import time
from dataclasses import asdict
from pathlib import Path

from scheduling.live import discover_gpus, run_campaign
from scheduling.live_store import (
    atomic_json,
    connect,
    digest,
    initialize,
    positive,
    settings_for,
    submit,
)
from scheduling.models import GPUDevice
from scheduling.simulator import _jain_fairness, _percentile

LIVE_POLICIES = ("fcfs", "token_sjf", "predicted_sjf", "fair_service", "uaf_sjf")


def report(root: Path, output: Path) -> dict:
    with connect(root) as db:
        db.execute("BEGIN")  # Consistent read snapshot while the coordinator may be active.
        settings = settings_for(db)
        jobs = [dict(row) for row in db.execute("SELECT * FROM jobs ORDER BY ready_at,job_id")]
        attempts = [dict(row) for row in db.execute("SELECT * FROM attempts ORDER BY claimed_at")]
    for row in jobs:
        row["spec"] = json.loads(row["spec"])
    for row in attempts:
        row["receipt"] = json.loads(row["receipt"]) if row["receipt"] else None
    counts = {status: sum(j["status"] == status for j in jobs)
              for status in ("QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "UNSCHEDULABLE")}
    completed = counts["QUEUED"] + counts["RUNNING"] == 0
    success_flows, waits, service = [], [], []
    owner_flows = {}
    owner_slowdowns = {}
    table = []
    for job in jobs:
        entries = [a for a in attempts if a["job_id"] == job["job_id"]]
        measured_service = sum(
            (a["receipt"] or {}).get("runtime_seconds") or 0 for a in entries
        )
        first_start = min((a["claimed_at"] for a in entries), default=None)
        end = max((a["finished_at"] or 0 for a in entries), default=0) or None
        flow = end - job["ready_at"] if job["status"] == "SUCCEEDED" else None
        wait = first_start - job["ready_at"] if first_start is not None else None
        table.append({
            "job_id": job["job_id"], "owner_id": job["owner_id"], "status": job["status"],
            "attempts": len(entries), "ready_at": job["ready_at"],
            "first_dispatch_at": first_start, "finished_at": end,
            "initial_wait_seconds": wait, "successful_flow_seconds": flow,
            "measured_attempt_service_seconds": measured_service,
            "published_attempt": job["published_attempt"], "reason": job["reason"],
        })
        if wait is not None:
            waits.append(wait)
        if flow is not None:
            success_flows.append(flow)
            owner_flows.setdefault(job["owner_id"], []).append(flow)
            if measured_service > 0:
                owner_slowdowns.setdefault(job["owner_id"], []).append(flow / measured_service)
        service.append(measured_service)
    start = min((j["ready_at"] for j in jobs), default=None)
    end = max((a["finished_at"] or 0 for a in attempts), default=0) or None
    duration = end - start if start is not None and end is not None else None
    def mean(values):
        return statistics.mean(values) if values else None
    metrics = {
        "counts": counts, "all_terminal": completed, "accepted_jobs": len(jobs),
        "attempt_count": len(attempts),
        "mean_initial_wait_seconds": mean(waits),
        "p95_initial_wait_seconds": _percentile(waits, .95) if waits else None,
        "waits_at_or_above_aging_threshold": sum(w >= settings["aging_seconds"] for w in waits),
        "mean_successful_flow_seconds": mean(success_flows),
        "p95_successful_flow_seconds": _percentile(success_flows, .95) if success_flows else None,
        "campaign_observed_seconds": duration,
        "successful_jobs_per_hour": len(success_flows) * 3600 / duration if duration else None,
        "measured_attempt_service_seconds": sum(service),
        "worker_occupancy_fraction": (
            sum(service) / (duration * len(settings["gpus"])) if duration and completed else None
        ),
        "mean_successful_flow_by_owner": {k: mean(v) for k, v in owner_flows.items()},
        "inverse_mean_slowdown_jain_successful_only": _jain_fairness(
            [1 / mean(v) for v in owner_slowdowns.values()]
        ) if owner_slowdowns else None,
        "attempts_without_runtime_measurement": sum(
            a["status"] != "RUNNING" and (a["receipt"] or {}).get("runtime_seconds") is None
            for a in attempts
        ),
    }
    payload = {
        "schema_version": "1.0", "evidence_type": (
            "mock_worker_functional_test" if settings["backend"] == "mock" else "live_boltz_execution"
        ),
        "exported_at": time.time(), "settings": settings, "metrics": metrics,
        "jobs": jobs, "attempts": attempts,
        "limitations": [
            "Worker occupancy is not sampled CUDA utilization.",
            "Initial wait ends at first dispatch; successful flow includes retries and their delays.",
            "Success-only flow/fairness metrics must be read alongside failed/unschedulable counts.",
            "Sampled device memory includes other GPU activity and may miss brief peaks.",
            "No hard quotas, preemption, or multi-node guarantees.",
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    atomic_json(output / "report.json", payload)
    with (output / "jobs.csv").open("w", newline="") as handle:
        if table:
            writer = csv.DictWriter(handle, fieldnames=list(table[0]))
            writer.writeheader()
            writer.writerows(table)
    atomic_json(output / "summary.json", {"evidence_type": payload["evidence_type"], **metrics})
    profiles = output / "profiles"
    profiles.mkdir(exist_ok=True)
    jobs_by_id = {job["job_id"]: job for job in jobs}
    for attempt in attempts:
        receipt = attempt["receipt"] or {}
        spec = jobs_by_id[attempt["job_id"]]["spec"]
        record = {
            "inference_seed": settings.get("inference_seed"),
            "biological_group_id": spec.get("biological_group_id", ""),
            "split": spec.get("split", ""),
            "benchmark_sha256": spec.get("benchmark_sha256", ""),
            "hardware": settings.get("hardware_label", ""),
            "schema_version": "1.0", "evidence_type": payload["evidence_type"],
            "job_id": attempt["job_id"], "owner_id": jobs_by_id[attempt["job_id"]]["owner_id"],
            "repeat": attempt["ordinal"], "status": attempt["status"],
            "features": spec["features"], "input_hashes": spec["input_hashes"],
            "actual_runtime_seconds": receipt.get("runtime_seconds"),
            # Conservative sampled whole-device memory, not the baseline-subtracted value.
            "actual_peak_memory_gib": receipt.get("peak_device_memory_gib"),
            "gpu_id": attempt["gpu_id"], "return_code": receipt.get("return_code"),
        }
        atomic_json(profiles / f"{attempt['attempt_id']}.json", record)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("root", type=Path)
    init.add_argument("--policy", choices=LIVE_POLICIES, default="uaf_sjf")
    init.add_argument("--mock", action="store_true")
    init.add_argument("--mock-gpus", type=int, default=4)
    init.add_argument("--gpu-ids", help="comma-separated physical GPU UUIDs; default all visible GPUs")
    init.add_argument("--cache", type=Path, default=Path("/workspace/cache"))
    init.add_argument("--lock-dir", type=Path,
                      default=Path(os.environ.get(
                          "HELIXFLOW_LOCK_DIR", f"/tmp/helixflow-gpu-locks-{os.getuid()}"
                      )))
    init.add_argument("--memory-safety", type=float, default=0.9)
    init.add_argument("--aging-seconds", type=float, default=3600)
    init.add_argument("--fairness-weight", type=float, default=0.25)
    init.add_argument("--sample-interval", type=float, default=0.5)
    init.add_argument("--hardware-label", help="explicit hardware provenance; default GPU model name")
    enqueue = commands.add_parser("submit")
    enqueue.add_argument("root", type=Path)
    enqueue.add_argument("manifest", type=Path)
    enqueue.add_argument("--model", type=Path,
                         help="optional TRUSTED predictor pickle; replaces manual predictions")
    run = commands.add_parser("run")
    run.add_argument("root", type=Path)
    run.add_argument("--watch", action="store_true")
    run.add_argument("--poll", type=float, default=0.1)
    status = commands.add_parser("status")
    status.add_argument("root", type=Path)
    export = commands.add_parser("export")
    export.add_argument("root", type=Path)
    export.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == "init":
        from scheduling.policies import make_policy
        make_policy(args.policy, memory_safety_fraction=args.memory_safety,
                    starvation_threshold_seconds=positive(args.aging_seconds, "aging_seconds"),
                    fairness_weight=args.fairness_weight)
        if not 0 <= args.fairness_weight < float("inf"):
            raise ValueError("fairness weight must be finite and nonnegative")
        if args.mock:
            if args.mock_gpus < 1:
                raise ValueError("mock GPU count must be positive")
            devices = [GPUDevice(f"mock-{i}", 16) for i in range(args.mock_gpus)]
        else:
            devices = discover_gpus()
            if args.gpu_ids:
                requested = set(args.gpu_ids.split(","))
                devices = [g for g in devices if g.gpu_id in requested]
                if {g.gpu_id for g in devices} != requested:
                    raise ValueError("one or more requested GPU UUIDs were not found")
            if not devices:
                raise ValueError("no GPUs discovered")
        versions = {}
        for package in ("boltz", "torch", "numpy", "scikit-learn", "PyYAML"):
            try:
                versions[package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                versions[package] = None
        package_root = Path(__file__).resolve().parents[1]
        source_hashes = {
            str(path.relative_to(package_root)): digest(path)
            for directory in ("scheduling", "experiments")
            for path in sorted((package_root / directory).glob("*.py"))
        }
        initialize(root, {
            "inference_seed": 42,
            "hardware_label": args.hardware_label or ("mock" if args.mock else ",".join(sorted(set(
                subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                               check=True, capture_output=True, text=True).stdout.strip().splitlines()
            )))),
            "backend": "mock" if args.mock else "boltz", "policy": args.policy,
            "gpus": [asdict(g) for g in devices], "cache": str(args.cache.resolve()),
            "lock_dir": str(args.lock_dir.resolve()), "memory_safety": args.memory_safety,
            "aging_seconds": args.aging_seconds, "fairness_weight": args.fairness_weight,
            "sample_interval": positive(args.sample_interval, "sample_interval"),
            "created_at": time.time(), "python": platform.python_version(),
            "platform": platform.platform(),
            "package_versions": versions, "source_sha256": source_hashes,
            "nvidia_smi": None if args.mock else subprocess.run(
                ["nvidia-smi"], capture_output=True, text=True, check=True
            ).stdout,
        })
        print(f"Initialized {root} ({len(devices)} devices; backend={'mock' if args.mock else 'boltz'})")
    elif args.command == "submit":
        print(f"Accepted {submit(root, args.manifest.resolve(), args.model)} jobs")
    elif args.command == "run":
        run_campaign(root, poll=positive(args.poll, "poll"), watch=args.watch)
    elif args.command == "status":
        with connect(root) as db:
            print(json.dumps([dict(r) for r in db.execute(
                "SELECT job_id,owner_id,status,attempt_count,reason,published_attempt FROM jobs"
            )], indent=2))
    else:
        print(json.dumps(report(root, args.output.resolve())["metrics"], indent=2))


if __name__ == "__main__":
    main()
