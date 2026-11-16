"""Synthetic scheduling shakedown, NOT a Boltz benchmark or runtime forecast.

Run from multi_gpu_scheduler with:
python3 -m experiments.local_scheduling_shakedown --output results/local-shakedown

Uses only the standard library and existing scheduling primitives. All jobs are
queued at time zero and fit every device, avoiding the existing arrival-event
and incompatible-aged-job defects. No trained predictor or GPU is used.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
import time
from collections import defaultdict
from itertools import pairwise
from pathlib import Path

from scheduling.models import GPUDevice, JobFeatures, RuntimePrediction, SchedulingJob
from scheduling.policies import POLICIES, make_policy
from scheduling.simulator import simulate


def workload(seed: int, count: int) -> list[SchedulingJob]:
    rng = random.Random(seed)
    jobs = []
    for index in range(count):
        # Assumed durations, memory, tokens, owners, and forecast errors: not measurements.
        runtime = math.exp(rng.uniform(math.log(30), math.log(600)))
        memory = rng.uniform(2, 12)
        forecast = runtime * math.exp(rng.gauss(0, 0.30))
        tokens = max(1, round(200 * math.sqrt(runtime / 60) * rng.uniform(0.5, 1.5)))
        jobs.append(SchedulingJob(
            job_id=f"job-{index:03d}",
            owner_id=f"researcher-{rng.randrange(4)}",
            submitted_at=0,
            features=JobFeatures(
                job_type="synthetic", total_residues=tokens,
                max_chain_length=tokens, estimated_tokens=tokens,
            ),
            prediction=RuntimePrediction(forecast, forecast * 1.35, memory * 1.10),
            actual_runtime_seconds=runtime,
            actual_peak_memory_gib=memory,
        ))
    return jobs


def check_assignments(jobs, devices, result) -> None:
    """Check accounting, placement, and no concurrent assignments on one device."""
    expected = {job.job_id: job for job in jobs}
    assert len(result.assignments) == len(expected)
    assert {a.job_id for a in result.assignments} == set(expected)
    by_gpu = defaultdict(list)
    capacity = {gpu.gpu_id: gpu.memory_gib for gpu in devices}
    for assignment in result.assignments:
        assert assignment.started_at >= assignment.submitted_at
        assert assignment.actual_peak_memory_gib <= capacity[assignment.gpu_id]
        assert math.isclose(
            assignment.service_seconds,
            expected[assignment.job_id].actual_runtime_seconds,
        )
        by_gpu[assignment.gpu_id].append(assignment)
    for assignments in by_gpu.values():
        ordered = sorted(assignments, key=lambda a: a.started_at)
        assert all(a.finished_at <= b.started_at for a, b in pairwise(ordered))
    assert 0 < result.metrics.gpu_utilization <= 1.00000001


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=40)
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--gpu-memory-gib", type=float, default=15.92)
    args = parser.parse_args()
    if args.jobs < 1 or args.seeds < 1 or args.gpu_memory_gib < 15:
        parser.error("positive jobs/seeds and at least 15 GiB/device are required")
    # Preserve previous evidence rather than silently replacing it.
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    rows = []
    workloads = []
    for seed in range(args.seeds):
        jobs = workload(seed, args.jobs)
        workloads.append({
            "seed": seed,
            "jobs": [{
                "job_id": j.job_id, "owner_id": j.owner_id,
                "submitted_at": j.submitted_at, "tokens": j.features.estimated_tokens,
                "assumed_runtime_seconds": j.actual_runtime_seconds,
                "assumed_memory_gib": j.actual_peak_memory_gib,
                "mock_p50_seconds": j.prediction.runtime_p50_seconds,
                "mock_p90_seconds": j.prediction.runtime_p90_seconds,
                "mock_memory_p90_gib": j.prediction.memory_p90_gib,
            } for j in jobs],
        })
        for gpu_count in (1, 2, 4):
            devices = [GPUDevice(f"gpu-{i}", args.gpu_memory_gib) for i in range(gpu_count)]
            for name in POLICIES:
                result = simulate(jobs, devices, make_policy(name),
                                  starvation_threshold_seconds=3600)
                check_assignments(jobs, devices, result)
                rows.append({"seed": seed, "gpus": gpu_count, **result.as_dict()})
    elapsed = time.perf_counter() - started
    caveats = [
        "SYNTHETIC ONLY: no Boltz predictions or physical multi-GPU execution performed.",
        "No measured profiles or trained model: durations are assumed log-uniform 30..600 s.",
        "Mock forecasts use assumed log-normal error sigma=0.30 and p90=1.35*p50; not calibrated quantiles.",
        "Memory is assumed uniform 2..12 GiB, forecast 1.10x; all jobs fit all devices.",
        "Tokens are synthetic duration-correlated proxies, not extracted biological features.",
        "Four randomly assigned owners, no entitlements or researcher quotas.",
        "Identical GPU speed=1, one job/device, no shared CPU/I/O contention or dispatch overhead.",
        "All arrivals at time zero: this scenario does not evaluate staggered arrivals.",
        "All jobs fit: this scenario does not evaluate incompatible-aged-job handling.",
        "The 3600 s aging threshold is not a guaranteed upper bound on waiting.",
        "Seed ranges show synthetic workload sensitivity, not empirical confidence intervals.",
        "Oracle-SJF knows assumed durations; it is a reference, not a deployable policy or universal optimum.",
        "Idle-host nvidia-smi memory is not a measured Boltz memory profile.",
    ]
    payload = {
        "evidence_type": "synthetic_functional_shakedown",
        "jobs_per_workload": args.jobs, "seeds": args.seeds,
        "gpu_memory_gib": args.gpu_memory_gib,
        "aging_seconds": 3600, "memory_safety_fraction": 0.9, "fairness_weight": 0.25,
        "simulation_wall_seconds": elapsed, "caveats": caveats,
        "workloads": workloads, "runs": rows,
    }
    (args.output / "simulation.json").write_text(json.dumps(payload, indent=2) + "\n")
    summaries = []
    for gpu_count in (1, 2, 4):
        for name in POLICIES:
            group = [r["metrics"] for r in rows if r["gpus"] == gpu_count and r["policy"] == name]
            summary = {"gpus": gpu_count, "policy": name}
            for metric in ("mean_waiting_seconds", "mean_flow_seconds", "p95_flow_seconds",
                           "makespan_seconds", "gpu_utilization", "jain_fairness", "starvation_count"):
                values = [m[metric] for m in group]
                summary[metric + "_mean"] = statistics.mean(values)
                summary[metric + "_min"] = min(values)
                summary[metric + "_max"] = max(values)
            summaries.append(summary)
    with (args.output / "summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)
    lines = ["SYNTHETIC scheduling shakedown — NOT measured Boltz performance", *caveats, "",
             f"{len(rows)} policy runs; {args.jobs} jobs/run; all accounting/overlap checks passed.",
             f"Simulation computation took {elapsed:.3f} seconds.", "",
             "GPUs Policy          Mean wait (min) Mean finish (min) Batch finish (min) Occupancy (%)"]
    for row in summaries:
        lines.append(
            f"{row['gpus']:4} {row['policy']:15} "
            f"{row['mean_waiting_seconds_mean']/60:15.2f} "
            f"{row['mean_flow_seconds_mean']/60:17.2f} "
            f"{row['makespan_seconds_mean']/60:18.2f} "
            f"{row['gpu_utilization_mean']*100:13.2f}"
        )
    report = "\n".join(lines) + "\n"
    (args.output / "report.txt").write_text(report)
    print(report)
    print(f"Artifacts: {args.output.resolve()}")


if __name__ == "__main__":
    main()
