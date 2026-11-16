#!/usr/bin/env python3
"""Create a simulation trace using strictly job-grouped out-of-fold predictions."""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

from experiments.prepare_simulation import arrival_times, features_from_row
from experiments.train_predictor import load_observations
from scheduling.predictor import train_predictor


def grouped_folds(job_ids: list[str], fold_count: int, seed: int) -> list[list[str]]:
    if fold_count < 2:
        raise ValueError("fold_count must be at least 2")
    if fold_count > len(job_ids):
        raise ValueError("fold_count cannot exceed the number of distinct jobs")
    shuffled = sorted(job_ids)
    random.Random(seed).shuffle(shuffled)
    return [shuffled[index::fold_count] for index in range(fold_count)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("profiles", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--calibration-fraction", type=float, default=0.2)
    parser.add_argument("--arrival", choices=("saturated", "poisson", "burst"), default="poisson")
    parser.add_argument("--rate", type=float, default=0.02)
    parser.add_argument("--owners", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.owners < 1:
        raise ValueError("owners must be positive")

    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    with args.profiles.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            grouped[row["job_id"]].append(row)
    observations = load_observations(args.profiles)
    job_groups = {o.job_id: o.biological_group_id or o.job_id for o in observations}
    for observation in observations:
        if job_groups[observation.job_id] != (observation.biological_group_id or observation.job_id):
            raise ValueError("job has inconsistent biological groups")
    folds = grouped_folds(sorted(set(job_groups.values())), args.folds, args.seed)
    predictions = {}
    fold_reports = []
    for fold_index, test_groups in enumerate(folds):
        test_ids = {job for job, group in job_groups.items() if group in test_groups}
        training = [item for item in observations if item.job_id not in test_ids]
        result = train_predictor(
            training,
            calibration_fraction=args.calibration_fraction,
            seed=args.seed + fold_index,
        )
        for job_id in test_ids:
            predictions[job_id] = result.predictor.predict(
                features_from_row(grouped[job_id][0])
            )
        fold_reports.append(
            {
                "fold": fold_index,
                "test_biological_groups": test_groups,
                "test_job_ids": sorted(test_ids),
                "training_job_ids": list(result.predictor.training_job_ids),
                "calibration_job_ids": list(result.calibration_job_ids),
                "calibration_runtime_p90_coverage": result.runtime_p90_coverage,
                "calibration_memory_p90_coverage": result.memory_p90_coverage,
            }
        )

    randomizer = random.Random(args.seed + 10_000)
    ordered_ids = sorted(grouped)
    randomizer.shuffle(ordered_ids)
    submitted = arrival_times(len(ordered_ids), args.arrival, args.rate, randomizer)
    rows = []
    for index, (job_id, submitted_at) in enumerate(zip(ordered_ids, submitted, strict=True)):
        repeats = grouped[job_id]
        features = features_from_row(repeats[0])
        if any(features_from_row(row) != features for row in repeats[1:]):
            raise ValueError(f"repetitions of {job_id} have inconsistent features")
        prediction = predictions[job_id]
        rows.append(
            {
                "job_id": job_id,
                "owner_id": f"researcher-{index % args.owners}",
                "submitted_at": submitted_at,
                **asdict(features),
                "runtime_p50_seconds": prediction.runtime_p50_seconds,
                "runtime_p90_seconds": prediction.runtime_p90_seconds,
                "memory_p90_gib": prediction.memory_p90_gib,
                "actual_runtime_seconds": statistics.median(
                    float(row["actual_runtime_seconds"]) for row in repeats
                ),
                "actual_peak_memory_gib": max(
                    float(row["actual_peak_memory_gib"]) for row in repeats
                ),
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    runtime_coverage = statistics.mean(
        row["actual_runtime_seconds"] <= row["runtime_p90_seconds"] for row in rows
    )
    memory_coverage = statistics.mean(
        row["actual_peak_memory_gib"] <= row["memory_p90_gib"] for row in rows
    )
    runtime_mae = statistics.mean(
        abs(row["actual_runtime_seconds"] - row["runtime_p50_seconds"]) for row in rows
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "method": "grouped_cross_fitting",
                "grouping": "biological_group_id when available, otherwise legacy job_id",
                "seed": args.seed,
                "fold_count": args.folds,
                "distinct_jobs": len(rows),
                "runtime_p50_mae_seconds": runtime_mae,
                "runtime_p90_coverage": runtime_coverage,
                "memory_p90_coverage": memory_coverage,
                "folds": fold_reports,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
