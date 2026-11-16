"""One coordinator per campaign, one leased worker per GPU, durable attempts.

Requires a local filesystem supporting SQLite WAL and flock. Not a multi-node
dispatcher. Workloads and manifests are trusted; do not expose as a public API.
"""

from __future__ import annotations

import fcntl
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .live_store import atomic_json, connect, digest, settings_for
from .models import GPUDevice, JobFeatures, RuntimePrediction, SchedulingJob
from .policies import make_policy


def lease(path: Path) -> int | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    return fd


def discover_gpus() -> list[GPUDevice]:
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=uuid,memory.total", "--format=csv,noheader,nounits"],
        check=True, text=True, capture_output=True, timeout=10,
    )
    return [
        GPUDevice(parts[0].strip(), float(parts[1]) / 1024)
        for line in result.stdout.splitlines() if (parts := line.split(","))
    ]


def busy_gpus() -> set[str]:
    result = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=gpu_uuid", "--format=csv,noheader"],
        check=True, text=True, capture_output=True, timeout=10,
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def as_job(row) -> SchedulingJob:
    spec = json.loads(row["spec"])
    # Actual values are unknown online and MUST NOT influence placement.
    # Oracle-SJF is deliberately excluded from live CLI policies.
    return SchedulingJob(
        row["job_id"], row["owner_id"], row["ready_at"],
        JobFeatures(**spec["features"]), RuntimePrediction(**spec["prediction"]),
        actual_runtime_seconds=1, actual_peak_memory_gib=1,
    )


def finalize(db, row, receipt: dict) -> None:
    spec = json.loads(row["spec"])
    success = receipt["status"] == "SUCCEEDED"
    next_status = "SUCCEEDED" if success else (
        "QUEUED" if row["ordinal"] < spec["max_attempts"] else "FAILED"
    )
    # A recovered receipt cannot regress/overwrite an already finalized attempt.
    with db:
        updated = db.execute(
            "UPDATE attempts SET status=?,finished_at=?,receipt=? "
            "WHERE attempt_id=? AND status='RUNNING'",
            (receipt["status"], receipt["finished_at"], json.dumps(receipt), row["attempt_id"]),
        ).rowcount
        if updated:
            db.execute(
                "UPDATE jobs SET status=?,reason=?,published_attempt=? WHERE job_id=?",
                (next_status, receipt.get("reason"), row["attempt_id"] if success else None,
                 row["job_id"]),
            )


def reconcile(db, root: Path, lock_dir: Path) -> None:
    rows = db.execute(
        "SELECT a.*,j.spec FROM attempts a JOIN jobs j USING(job_id) WHERE a.status='RUNNING'"
    ).fetchall()
    for row in rows:
        folder = root / "attempts" / row["attempt_id"]
        receipt_path = folder / "receipt.json"
        if receipt_path.is_file():
            try:
                receipt = json.loads(receipt_path.read_text())
                if receipt["attempt_id"] != row["attempt_id"] or receipt["job_id"] != row["job_id"]:
                    raise ValueError("attempt receipt identity mismatch")
                if receipt["status"] == "SUCCEEDED":
                    if not receipt["artifacts"]:
                        raise ValueError("empty success artifact inventory")
                    for name, expected in receipt["artifacts"].items():
                        path = folder / "output" / name
                        if not path.resolve().is_relative_to((folder / "output").resolve()):
                            raise ValueError("unsafe artifact path")
                        if digest(path) != expected:
                            raise ValueError("output hash mismatch")
                finalize(db, row, receipt)
            except (ValueError, OSError, KeyError, TypeError) as exc:
                finalize(db, row, {
                    "status": "FAILED", "finished_at": time.time(),
                    "reason": f"invalid receipt/artifacts: {exc}", "runtime_seconds": None,
                })
            continue
        # If a surviving worker or its child holds the lease, leave it alone.
        # No PID reuse assumptions or blind retry of a potentially active GPU job.
        fd = lease(lock_dir / f"{row['gpu_id']}.lock")
        if fd is not None:
            os.close(fd)
            finalize(db, row, {
                "status": "INTERRUPTED", "finished_at": time.time(),
                "reason": "GPU lease released without a receipt; interrupted attempt",
                "runtime_seconds": None,
            })


def owner_service(db) -> dict[str, float]:
    result = {}
    for row in db.execute(
        "SELECT a.*,j.owner_id FROM attempts a JOIN jobs j USING(job_id)"
    ):
        receipt = json.loads(row["receipt"]) if row["receipt"] else {}
        measured = receipt.get("runtime_seconds")
        # Missing measurements (e.g. hard kill) retain a documented estimate.
        amount = measured if measured is not None else row["reserved_seconds"]
        owner = row["owner_id"]
        result[owner] = result.get(owner, 0) + amount
    return result


def run_campaign(root: Path, *, poll: float = 0.1, watch: bool = False) -> None:
    root = root.resolve()
    coordinator_fd = lease(root / "coordinator.lock")
    if coordinator_fd is None:
        raise RuntimeError("another coordinator already owns this campaign")
    children = []
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    old_handlers = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        with connect(root) as db:
            settings = settings_for(db)
            lock_dir = Path(settings["lock_dir"])
            devices = [GPUDevice(**gpu) for gpu in settings["gpus"]]
            if settings["backend"] == "boltz":
                available = {gpu.gpu_id: gpu for gpu in discover_gpus()}
                for device in devices:
                    if device.gpu_id not in available:
                        raise RuntimeError(f"configured GPU is absent: {device.gpu_id}")
                    if device.memory_gib > available[device.gpu_id].memory_gib:
                        raise RuntimeError("configured memory exceeds physical GPU capacity")
            policy = make_policy(
                settings["policy"], memory_safety_fraction=settings["memory_safety"],
                starvation_threshold_seconds=settings["aging_seconds"],
                fairness_weight=settings["fairness_weight"],
            )
            while True:
                children = [child for child in children if child.poll() is None]
                reconcile(db, root, lock_dir)
                if stopping:
                    # Drain before exiting, including surviving workers from an earlier
                    # coordinator. Container PID 1 must not exit while workers are active.
                    active = db.execute(
                        "SELECT count(*) FROM attempts WHERE status='RUNNING'"
                    ).fetchone()[0]
                    if not active:
                        break
                    time.sleep(poll)
                    continue
                now = time.time()
                waiting = db.execute(
                    "SELECT * FROM jobs WHERE status='QUEUED' AND ready_at<=? "
                    "ORDER BY ready_at,job_id", (now,),
                ).fetchall()
                feasible = []
                for row in waiting:
                    job = as_job(row)
                    if not any(job.prediction.memory_p90_gib <=
                               gpu.memory_gib * settings["memory_safety"] for gpu in devices):
                        with db:
                            db.execute(
                                "UPDATE jobs SET status='UNSCHEDULABLE',reason=? WHERE job_id=?",
                                ("prediction exceeds every configured GPU's memory allowance",
                                 row["job_id"]),
                            )
                    else:
                        feasible.append(row)
                foreign_busy = busy_gpus() if settings["backend"] == "boltz" else set()
                locks = {}
                try:
                    for gpu in devices:
                        if gpu.gpu_id not in foreign_busy:
                            fd = lease(lock_dir / f"{gpu.gpu_id}.lock")
                            if fd is not None:
                                locks[gpu.gpu_id] = fd
                    while feasible and locks and not stopping:
                        decision = policy.choose(
                            [as_job(row) for row in feasible],
                            [gpu for gpu in devices if gpu.gpu_id in locks],
                            time.time(), owner_service(db),
                        )
                        if decision is None:
                            break
                        row = next(r for r in feasible if r["job_id"] == decision.job_id)
                        feasible.remove(row)
                        spec = json.loads(row["spec"])
                        attempt_id = uuid.uuid4().hex
                        folder = root / "attempts" / attempt_id
                        folder.mkdir()
                        request = {
                            "attempt_id": attempt_id, "job_id": row["job_id"],
                            "ordinal": row["attempt_count"] + 1, "spec": spec,
                            "gpu_id": decision.gpu_id, "backend": settings["backend"],
                            "cache": settings["cache"], "sample_interval": settings["sample_interval"],
                        }
                        atomic_json(folder / "request.json", request)
                        # Persist claim before launching: on a crash, recovery either
                        # observes the worker lease/receipt or records an interruption.
                        with db:
                            db.execute(
                                "INSERT INTO attempts(attempt_id,job_id,ordinal,gpu_id,status,"
                                "claimed_at,reserved_seconds) VALUES(?,?,?,?,?,?,?)",
                                (attempt_id, row["job_id"], request["ordinal"], decision.gpu_id,
                                 "RUNNING", time.time(), spec["prediction"]["runtime_p90_seconds"]),
                            )
                            db.execute(
                                "UPDATE jobs SET status='RUNNING',attempt_count=attempt_count+1 "
                                "WHERE job_id=?", (row["job_id"],),
                            )
                        fd = locks.pop(decision.gpu_id)
                        try:
                            with (folder / "supervisor.log").open("w") as log:
                                children.append(subprocess.Popen(
                                    [sys.executable, "-m", "scheduling.live_worker",
                                     str(folder / "request.json"), "--lock-fd", str(fd)],
                                    stdout=log, stderr=subprocess.STDOUT,
                                    start_new_session=True, pass_fds=(fd,),
                                ))
                        finally:
                            os.close(fd)
                finally:
                    for fd in locks.values():
                        os.close(fd)
                pending = db.execute(
                    "SELECT count(*) FROM jobs WHERE status IN ('QUEUED','RUNNING')"
                ).fetchone()[0]
                if not pending and not watch:
                    break
                time.sleep(poll)
    finally:
        # SIGTERM/SIGINT drain active attempts and leave queued jobs for resume.
        # SIGKILL recovery relies on inherited GPU leases and durable receipts.
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
        os.close(coordinator_fd)
