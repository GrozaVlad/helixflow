#!/usr/bin/env python3
"""Replay measured Boltz jobs under one or more multi-GPU scheduling policies."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from scheduling.models import GPUDevice, JobFeatures, RuntimePrediction, SchedulingJob
from scheduling.policies import POLICIES, make_policy
from scheduling.simulator import simulate


def load_jobs(path: Path) -> list[SchedulingJob]:
    jobs = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            features = JobFeatures(
                job_type=row["job_type"],
                total_residues=int(row["total_residues"]),
                max_chain_length=int(row["max_chain_length"]),
                protein_chains=int(row.get("protein_chains") or 1),
                ligand_count=int(row.get("ligand_count") or 0),
                ligand_atoms=int(row.get("ligand_atoms") or 0),
                msa_depth=int(row.get("msa_depth") or 0),
                estimated_tokens=int(row.get("estimated_tokens") or row["total_residues"]),
                input_bytes=int(row.get("input_bytes") or 0),
                recycling_steps=int(row.get("recycling_steps") or 3),
                sampling_steps=int(row.get("sampling_steps") or 200),
                diffusion_samples=int(row.get("diffusion_samples") or 1),
            )
            jobs.append(
                SchedulingJob(
                    job_id=row["job_id"],
                    owner_id=row["owner_id"],
                    submitted_at=float(row["submitted_at"]),
                    features=features,
                    prediction=RuntimePrediction(
                        runtime_p50_seconds=float(row["runtime_p50_seconds"]),
                        runtime_p90_seconds=float(row["runtime_p90_seconds"]),
                        memory_p90_gib=float(row["memory_p90_gib"]),
                    ),
                    actual_runtime_seconds=float(row["actual_runtime_seconds"]),
                    actual_peak_memory_gib=float(row["actual_peak_memory_gib"]),
                )
            )
    return jobs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("profiles", type=Path, help="CSV containing measured jobs and predictions")
    parser.add_argument("--policy", choices=(*POLICIES, "all"), default="all")
    parser.add_argument("--gpus", type=int, default=4)
    parser.add_argument("--gpu-memory-gib", type=float, default=24.0)
    parser.add_argument("--starvation-seconds", type=float, default=3600.0)
    parser.add_argument("--memory-safety", type=float, default=0.9)
    parser.add_argument("--fairness-weight", type=float, default=0.25)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    jobs = load_jobs(args.profiles)
    gpus = [GPUDevice(f"gpu-{index}", args.gpu_memory_gib) for index in range(args.gpus)]
    names = POLICIES if args.policy == "all" else (args.policy,)
    results = []
    for name in names:
        policy = make_policy(
            name,
            starvation_threshold_seconds=args.starvation_seconds,
            memory_safety_fraction=args.memory_safety,
            fairness_weight=args.fairness_weight,
        )
        results.append(
            simulate(
                jobs,
                gpus,
                policy,
                starvation_threshold_seconds=args.starvation_seconds,
            ).as_dict()
        )

    payload = json.dumps({"schema_version": "1.0", "results": results}, indent=2)
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)


if __name__ == "__main__":
    main()
