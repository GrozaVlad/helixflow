"""Detached attempt supervisor; the GPU lease survives dispatcher termination."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
from pathlib import Path

import yaml

from .live_store import atomic_json, digest


def sample_gpu(gpu_id: str) -> dict:
    result = subprocess.run(
        ["nvidia-smi", f"--id={gpu_id}", "--query-gpu=memory.used,utilization.gpu",
         "--format=csv,noheader,nounits"],
        check=True, text=True, capture_output=True, timeout=5,
    )
    memory, utilization = map(float, result.stdout.strip().split(","))
    return {"epoch": time.time(), "memory_mib": memory, "utilization_percent": utilization}


def artifacts(output: Path) -> dict[str, str]:
    candidates = sorted(output.glob("boltz_results_*/predictions/*/*_model_*.cif"))
    if not candidates or any(path.stat().st_size == 0 for path in candidates):
        raise ValueError("no nonempty predicted structure produced")
    confidence = sorted(output.glob("boltz_results_*/predictions/*/confidence_*.json"))
    if not confidence:
        raise ValueError("no confidence artifact produced")
    for path in confidence:
        data = json.loads(path.read_text())
        if not isinstance(data, dict) or "confidence_score" not in data:
            raise ValueError("invalid confidence artifact")
    paths = [p for p in output.rglob("*") if p.is_file()]
    if any(p.is_symlink() or not p.resolve().is_relative_to(output.resolve()) for p in paths):
        raise ValueError("output contains an unsafe path")
    return {str(p.relative_to(output)): digest(p) for p in paths}


def run(request_path: Path, lock_fd: int) -> None:
    request = json.loads(request_path.read_text())
    folder = request_path.parent
    output = folder / "output"
    output.mkdir()
    started = time.time()
    started_mono = time.monotonic()
    stop = False

    def interrupted(_signum, _frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    spec = request["spec"]
    receipt = {
        "attempt_id": request["attempt_id"], "job_id": request["job_id"],
        "gpu_id": request["gpu_id"], "backend": request["backend"],
        "started_at": started, "status": "FAILED", "return_code": None,
        "reason": None, "artifacts": {}, "sample_errors": 0,
    }
    atomic_json(folder / "worker.json", {
        "pid": os.getpid(), "started_at": started, "attempt_id": request["attempt_id"],
    })
    process = None
    samples = []
    try:
        for path, expected in spec["input_hashes"].items():
            if digest(Path(path)) != expected:
                raise ValueError("staged scientific input was modified")
        if request["backend"] == "mock":
            duration = float(spec["mock"].get("duration_seconds", 0.05))
            while time.monotonic() - started_mono < duration and not stop:
                if time.monotonic() - started_mono >= spec["timeout_seconds"]:
                    raise TimeoutError("attempt timed out")
                time.sleep(0.01)
            if stop:
                raise InterruptedError("worker interrupted")
            if request["ordinal"] <= int(spec["mock"].get("fail_attempts", 0)):
                raise RuntimeError("injected mock failure")
            if spec["mock"].get("missing_artifacts"):
                raise ValueError("injected missing artifacts")
            (output / "MOCK_ONLY.txt").write_text("Not a scientific prediction.\n")
            receipt["artifacts"] = {"MOCK_ONLY.txt": digest(output / "MOCK_ONLY.txt")}
            receipt["return_code"] = 0
        else:
            command = [
                "boltz", "predict", spec["input"], "--out_dir", str(output),
                "--cache", request["cache"], "--devices", "1", "--accelerator", "gpu",
                "--max_parallel_samples", "1", "--num_workers", "0",
                "--preprocessing-threads", "2",
                "--seed", "42",
            ]
            for option, value in spec["options"].items():
                command.extend([f"--{option}", str(value)])
            receipt["command"] = command
            environment = os.environ.copy()
            environment["CUDA_VISIBLE_DEVICES"] = request["gpu_id"]
            environment["OMP_NUM_THREADS"] = "1"
            environment["MKL_NUM_THREADS"] = "1"
            runtime_cache = folder / "runtime-cache"
            runtime_cache.mkdir()
            environment["NUMBA_CACHE_DIR"] = str(runtime_cache / "numba")
            environment["XDG_CACHE_HOME"] = str(runtime_cache)
            environment["MPLCONFIGDIR"] = str(runtime_cache / "matplotlib")
            environment["CUDA_CACHE_PATH"] = str(runtime_cache / "cuda")
            environment["TRITON_CACHE_DIR"] = str(runtime_cache / "triton")
            environment["TRITON_DUMP_DIR"] = str(runtime_cache / "triton-dump")
            environment["TRITON_OVERRIDE_DIR"] = str(runtime_cache / "triton-override")
            environment["TORCHINDUCTOR_CACHE_DIR"] = str(runtime_cache / "inductor")
            receipt["runtime_cache_mode"] = "fresh-per-attempt"
            samples.append(sample_gpu(request["gpu_id"]))
            with (folder / "run.log").open("w") as log:
                # Inherit the lease into the workload too: a killed wrapper must
                # not release a GPU still occupied by its surviving child.
                process = subprocess.Popen(
                    command, env=environment, stdout=log, stderr=subprocess.STDOUT,
                    start_new_session=True, pass_fds=(lock_fd,),
                )
                receipt["workload_pid"] = process.pid
                while process.poll() is None:
                    if stop or time.monotonic() - started_mono >= spec["timeout_seconds"]:
                        os.killpg(process.pid, signal.SIGTERM)
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait()
                        if stop:
                            raise InterruptedError("worker interrupted")
                        raise TimeoutError("attempt timed out")
                    try:
                        samples.append(sample_gpu(request["gpu_id"]))
                    except (OSError, ValueError, subprocess.SubprocessError):
                        receipt["sample_errors"] += 1
                    remaining = spec["timeout_seconds"] - (time.monotonic() - started_mono)
                    time.sleep(max(0, min(request["sample_interval"], remaining, 1.0)))
                receipt["return_code"] = process.returncode
            if process.returncode != 0:
                raise RuntimeError(f"Boltz exited with code {process.returncode}; see run.log")
            receipt["artifacts"] = artifacts(output)
            document = yaml.safe_load(Path(spec["input"]).read_text())
            if any("affinity" in p for p in document.get("properties", [])):
                affinity = list(output.glob("boltz_results_*/predictions/*/affinity_*.json"))
                if not affinity or any(
                    not isinstance(json.loads(path.read_text()), dict) for path in affinity
                ):
                    raise ValueError("requested affinity output is missing or invalid")
        receipt["status"] = "SUCCEEDED"
    except Exception as exc:  # noqa: BLE001 -- attempt boundary persists every ordinary failure
        receipt["reason"] = f"{type(exc).__name__}: {exc}"
    finally:
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        finished = time.time()
        receipt.update(
            finished_at=finished, runtime_seconds=time.monotonic() - started_mono,
            telemetry_samples=len(samples),
            peak_device_memory_gib=max((s["memory_mib"] for s in samples), default=0) / 1024,
            peak_incremental_memory_gib=(
                max(s["memory_mib"] for s in samples) - samples[0]["memory_mib"]
            ) / 1024 if samples else None,
            mean_sampled_gpu_utilization=(
                sum(s["utilization_percent"] for s in samples) / len(samples)
            ) if samples else None,
        )
        atomic_json(folder / "telemetry.json", {"samples": samples})
        atomic_json(folder / "receipt.json", receipt)
        os.close(lock_fd)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("request", type=Path)
    parser.add_argument("--lock-fd", type=int, required=True)
    args = parser.parse_args()
    run(args.request, args.lock_fd)


if __name__ == "__main__":
    main()
