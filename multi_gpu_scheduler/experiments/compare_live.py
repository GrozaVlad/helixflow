"""Compare completed, matched live campaigns; never mix synthetic and real evidence."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def signature(report: dict) -> dict:
    return {
        job["job_id"]: {
            "owner": job["owner_id"], "source_sha256": job["spec"]["source_sha256"],
            "msa_hashes": sorted(
                value for path, value in job["spec"]["input_hashes"].items()
                if Path(path).suffix == ".a3m"
            ),
            "options": job["spec"]["options"],
            "prediction": job["spec"]["prediction"],
            "prediction_source": job["spec"].get("prediction_source"),
            "biological_group_id": job["spec"].get("biological_group_id"),
            "split": job["spec"].get("split"),
            "benchmark_sha256": job["spec"].get("benchmark_sha256"),
            "arrival_offset": round(job["ready_at"] - job["submitted_at"], 4),
            "timeout": job["spec"]["timeout_seconds"], "max_attempts": job["spec"]["max_attempts"],
        }
        for job in report["jobs"]
    }


def compare(paths: list[Path], *, allow_mock: bool = False) -> list[dict]:
    reports = [json.loads(path.read_text()) for path in paths]
    if not reports:
        raise ValueError("provide at least one report")
    kind = reports[0]["evidence_type"]
    if kind == "mock_worker_functional_test" and not allow_mock:
        raise ValueError("mock results require --allow-mock and are not performance evidence")
    reference = signature(reports[0])
    context_keys = ("hardware_label", "package_versions", "source_sha256", "cache_sha256", "inference_seed")
    context = {key: reports[0]["settings"].get(key) for key in context_keys}
    rows = []
    for path, report in zip(paths, reports, strict=True):
        if report["evidence_type"] != kind:
            raise ValueError("cannot mix real and mock evidence")
        if signature(report) != reference:
            raise ValueError("workloads/options/owners/predictions/arrivals are not matched")
        if {key: report["settings"].get(key) for key in context_keys} != context:
            raise ValueError("hardware, package, source, or model cache provenance differs")
        metrics = report["metrics"]
        if not metrics["all_terminal"]:
            raise ValueError("cannot compare an unfinished campaign")
        settings = report["settings"]
        rows.append({
            "source_report": str(path.resolve()), "evidence_type": kind,
            "policy": settings["policy"], "gpus": len(settings["gpus"]),
            **metrics["counts"],
            **{key: metrics[key] for key in (
                "attempt_count", "mean_initial_wait_seconds", "p95_initial_wait_seconds",
                "mean_successful_flow_seconds", "p95_successful_flow_seconds",
                "campaign_observed_seconds", "successful_jobs_per_hour",
                "worker_occupancy_fraction", "inverse_mean_slowdown_jain_successful_only",
                "attempts_without_runtime_measurement",
            )},
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--allow-mock", action="store_true")
    args = parser.parse_args()
    rows = compare(args.reports, allow_mock=args.allow_mock)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} campaign rows to {args.output}; inspect failures and provenance.")


if __name__ == "__main__":
    main()
