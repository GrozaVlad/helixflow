#!/usr/bin/env python3
"""Aggregate repeated profiles, predict resources, and generate an arrival trace."""

from __future__ import annotations

import argparse
import csv
import random
import statistics
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

from scheduling.models import JobFeatures
from scheduling.predictor import PredictorBundle


def features_from_row(row: dict[str, str]) -> JobFeatures:
    return JobFeatures(
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


def arrival_times(
    count: int,
    pattern: str,
    rate: float,
    randomizer: random.Random,
) -> list[float]:
    if pattern == "saturated":
        return [0.0] * count
    if rate <= 0:
        raise ValueError("rate must be positive for poisson and burst arrivals")
    if pattern == "poisson":
        values = []
        current = 0.0
        for _ in range(count):
            current += randomizer.expovariate(rate)
            values.append(current)
        return values
    burst_size = max(2, round(count**0.5))
    interval = burst_size / rate
    return [float(index // burst_size) * interval for index in range(count)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("profiles", type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--arrival", choices=("saturated", "poisson", "burst"), default="poisson")
    parser.add_argument("--rate", type=float, default=0.02, help="mean jobs per second")
    parser.add_argument("--owners", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.owners < 1:
        raise ValueError("owners must be positive")

    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    with args.profiles.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            grouped[row["job_id"]].append(row)
    if not grouped:
        raise ValueError("profiles file contains no jobs")

    predictor = PredictorBundle.load(args.model)
    randomizer = random.Random(args.seed)
    job_ids = sorted(grouped)
    randomizer.shuffle(job_ids)
    submitted = arrival_times(len(job_ids), args.arrival, args.rate, randomizer)
    rows = []
    for index, (job_id, submitted_at) in enumerate(zip(job_ids, submitted, strict=True)):
        repeats = grouped[job_id]
        features = features_from_row(repeats[0])
        prediction = predictor.predict(features)
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


if __name__ == "__main__":
    main()
