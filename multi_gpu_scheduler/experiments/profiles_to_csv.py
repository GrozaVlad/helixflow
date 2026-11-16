#!/usr/bin/env python3
"""Combine successful profiler JSON records into the model-training CSV schema."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("profiles", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    rows = []
    for path in sorted(args.profiles):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["status"] != "SUCCEEDED":
            continue
        if record.get("evidence_type") == "mock_worker_functional_test":
            raise ValueError("mock executions must never enter the resource training dataset")
        if any(
            record.get(key) is None or not math.isfinite(record[key]) or record[key] <= 0
            for key in ("actual_runtime_seconds", "actual_peak_memory_gib")
        ):
            raise ValueError(f"invalid or missing measured labels in {path}")
        rows.append(
            {
                "job_id": record["job_id"],
                "biological_group_id": record.get("biological_group_id", ""),
                "split": record.get("split", ""),
                "hardware": record.get("hardware", ""),
                "benchmark_sha256": record.get("benchmark_sha256", ""),
                "owner_id": record["owner_id"],
                "repeat": record["repeat"],
                **record["features"],
                "actual_runtime_seconds": record["actual_runtime_seconds"],
                "actual_peak_memory_gib": record["actual_peak_memory_gib"],
            }
        )
    if not rows:
        raise SystemExit("no successful profile records")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
