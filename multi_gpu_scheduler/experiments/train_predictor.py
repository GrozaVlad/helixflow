#!/usr/bin/env python3
"""Train calibrated runtime and VRAM quantile models from measured job profiles."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path

from scheduling.models import JobFeatures
from scheduling.predictor import TrainingObservation, train_predictor


def load_observations(path: Path) -> list[TrainingObservation]:
    observations = []
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
            observations.append(
                TrainingObservation(
                    job_id=row["job_id"],
                    features=features,
                    runtime_seconds=float(row["actual_runtime_seconds"]),
                    peak_memory_gib=float(row["actual_peak_memory_gib"]),
                    biological_group_id=row.get("biological_group_id", ""),
                    split=row.get("split", ""),
                    hardware=row.get("hardware", ""),
                    benchmark_sha256=row.get("benchmark_sha256", ""),
                )
            )
    return observations


def plot_evaluation(observations, predictions, output):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output.mkdir(parents=True, exist_ok=True)
    entries = [
        {
            "job_id": o.job_id,
            "biological_group_id": o.biological_group_id,
            "actual_runtime_seconds": o.runtime_seconds,
            "actual_memory_gib": o.peak_memory_gib,
            "runtime_p50_seconds": p.runtime_p50_seconds,
            "runtime_p90_seconds": p.runtime_p90_seconds,
            "memory_p90_gib": p.memory_p90_gib,
        }
        for o, p in zip(observations, predictions, strict=True)
    ]
    with (output / "held-out-predictions.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(entries[0]))
        writer.writeheader()
        writer.writerows(entries)
    figure, axes = plt.subplots(1, 2, figsize=(10, 4), layout="constrained")
    for ax, actual, estimate, label in (
        (axes[0], "actual_runtime_seconds", "runtime_p50_seconds", "Runtime p50 (s)"),
        (axes[1], "actual_memory_gib", "memory_p90_gib", "Memory p90 (GiB)"),
    ):
        xs, ys = [r[actual] for r in entries], [r[estimate] for r in entries]
        maximum = max(*xs, *ys)
        ax.scatter(xs, ys, alpha=0.6)
        ax.plot([0, maximum], [0, maximum], linestyle="--", color="grey")
        ax.set(xlabel="Measured " + label.split()[0].lower(), ylabel="Predicted " + label)
        ax.grid(alpha=0.2)
    figure.suptitle("Held-out biological groups; each point is one execution")
    figure.savefig(output / "predictor.png", dpi=160)
    figure.savefig(output / "predictor.svg")
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("profiles", type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--calibration-fraction", type=float, default=0.2)
    parser.add_argument("--explicit-splits", action="store_true")
    parser.add_argument(
        "--plots", type=Path, help="optional held-out PNG/SVG plots and per-observation CSV"
    )
    args = parser.parse_args()
    observations = load_observations(args.profiles)
    result = train_predictor(
        observations,
        seed=args.seed,
        calibration_fraction=args.calibration_fraction,
        explicit_splits=args.explicit_splits,
    )
    held_out = [o for o in observations if o.split == "test"] if args.explicit_splits else []
    predictions = [result.predictor.predict(o.features) for o in held_out]
    evaluation = (
        None
        if not held_out
        else {
            "observations": len(held_out),
            "jobs": len({o.job_id for o in held_out}),
            "groups": len({o.biological_group_id for o in held_out}),
            "runtime_p50_mae_seconds": statistics.mean(
                abs(o.runtime_seconds - p.runtime_p50_seconds)
                for o, p in zip(held_out, predictions, strict=True)
            ),
            "runtime_p90_coverage": statistics.mean(
                o.runtime_seconds <= p.runtime_p90_seconds
                for o, p in zip(held_out, predictions, strict=True)
            ),
            "memory_p90_coverage": statistics.mean(
                o.peak_memory_gib <= p.memory_p90_gib
                for o, p in zip(held_out, predictions, strict=True)
            ),
        }
    )
    if held_out:
        groups = {o.biological_group_id for o in held_out}
        evaluation["mean_group_runtime_p50_mae_seconds"] = statistics.mean(
            statistics.mean(
                abs(o.runtime_seconds - p.runtime_p50_seconds)
                for o, p in zip(held_out, predictions, strict=True)
                if o.biological_group_id == group
            )
            for group in groups
        )
        for resource, actual, predicted in (
            ("runtime", "runtime_seconds", "runtime_p90_seconds"),
            ("memory", "peak_memory_gib", "memory_p90_gib"),
        ):
            evaluation[f"{resource}_p90_group_coverage_all_repeats"] = statistics.mean(
                all(
                    getattr(o, actual) <= getattr(p, predicted)
                    for o, p in zip(held_out, predictions, strict=True)
                    if o.biological_group_id == group
                )
                for group in groups
            )
    if args.plots:
        if not held_out:
            raise ValueError("held-out plots require explicit splits with test observations")
        plot_evaluation(held_out, predictions, args.plots)
    args.model.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    result.predictor.save(args.model)
    args.report.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "provenance": result.predictor.provenance,
                "held_out_test": evaluation,
                "warning": "Calibration metrics are not held-out test accuracy.",
                "seed": args.seed,
                "training_job_ids": result.predictor.training_job_ids,
                "calibration_job_ids": result.calibration_job_ids,
                "runtime_p50_mae_seconds": result.runtime_p50_mae_seconds,
                "runtime_p90_coverage": result.runtime_p90_coverage,
                "memory_p90_coverage": result.memory_p90_coverage,
                "runtime_calibration_seconds": (result.predictor.runtime_calibration_seconds),
                "memory_calibration_gib": result.predictor.memory_calibration_gib,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
