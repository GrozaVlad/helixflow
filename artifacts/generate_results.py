"""Extract verified aggregate evidence and render the SoftwareX result figures.

Use --refresh-evidence to rebuild the snapshot from the bundled selected evidence.
Subsequent runs need only results/measurements.json and Matplotlib/NumPy.
No model checkpoints, alignments, credentials, or remote access are required.
"""

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

PAPER = Path(__file__).resolve().parent
EVIDENCE = PAPER / "results/measurements.json"
POLICIES = [
    "fcfs",
    "token_sjf",
    "predicted_sjf",
    "fair_service",
    "uaf_no_service",
    "uaf_sjf",
]
LABELS = [
    "FIFO",
    "Token-SJF",
    "Predicted-SJF",
    "Fair-service",
    "UAF, no service",
    "UAF-SJF",
]
COLORS = ["#595959", "#009E73", "#0072B2", "#CC79A7", "#E69F00", "#D55E00"]
MARKERS = ["o", "s", "^", "D", "v", "P"]


def read(path):
    return json.loads(path.read_text())


def extract():
    base = PAPER / "evidence"
    raw = base / "remote-results"
    study = raw / "phase-4-comparison"
    assert read(base / "comparison-backup-audit.json")["status"] == "PASSED"
    assert read(base / "recovery-backup-audit.json")["status"] == "PASSED"
    summary = read(study / "report/summary.json")
    assert summary["completed_trials"] == 108
    fields = [
        "trial_id",
        "trace",
        "repeat",
        "variant",
        "gpus",
        "SUCCEEDED",
        "FAILED",
        "UNSCHEDULABLE",
        "campaign_observed_seconds",
        "mean_initial_wait_seconds",
        "mean_successful_flow_seconds",
        "p95_successful_flow_seconds",
        "worker_occupancy_fraction",
        "inverse_mean_slowdown_jain_successful_only",
    ]
    trials = [{k: t[k] for k in fields} for t in summary["trials"]]
    assert all(
        t["SUCCEEDED"] == 12 and t["FAILED"] == t["UNSCHEDULABLE"] == 0 for t in trials
    )
    profile = raw / "phase-2-profiling"
    prediction_file = profile / "predictor-plots/held-out-predictions.csv"
    with prediction_file.open() as stream:
        predictions = list(csv.DictReader(stream))
    for row in predictions:
        for key in row:
            if key not in ("job_id", "biological_group_id"):
                row[key] = float(row[key])
    assert len(predictions) == 24 and len({r["job_id"] for r in predictions}) == 12
    sources = [
        study / "report/summary.json",
        study / "validation.json",
        profile / "predictor-report.json",
        prediction_file,
        raw / "phase-5-recovery-r3/phase.json",
        base / "recovery-backup-audit.json",
    ]
    fingerprints = {}
    for path in sources:
        with path.open("rb") as stream:
            fingerprints[str(path.relative_to(base))] = hashlib.file_digest(
                stream, "sha256"
            ).hexdigest()
    payload = {
        "schema_version": "1.0",
        "evidence_type": "measured_live_execution",
        "source_sha256": fingerprints,
        "trials": trials,
        "prediction_observations": predictions,
        "predictor": read(profile / "predictor-report.json")["held_out_test"],
        "recovery": read(raw / "phase-5-recovery-r3/phase.json"),
        "recovery_local_audit": read(base / "recovery-backup-audit.json"),
        "clean_install": read(
            base / "clean-install/validation.json"
        ),
        "limitations": [
            "Three trial repetitions; not independent biological samples.",
            "Twelve distinct held-out targets, one four-GPU host.",
            "Error bars show repetition ranges, not confidence intervals.",
        ],
    }
    EVIDENCE.parent.mkdir(exist_ok=True)
    EVIDENCE.write_text(json.dumps(payload, indent=2) + "\n")


def save(figure, stem):
    for extension in ("pdf", "png", "svg"):
        figure.savefig(
            PAPER / "figures" / f"{stem}.{extension}", dpi=220, bbox_inches="tight"
        )
    plt.close(figure)


def plot_results(data):
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.titlesize": 10,
            "axes.labelsize": 9,
            "legend.fontsize": 8,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )
    groups = defaultdict(list)
    for row in data["trials"]:
        groups[(row["trace"], row["gpus"], row["variant"])].append(row)
    assert all(len(v) == 3 for v in groups.values())
    fig, axes = plt.subplots(1, 2, figsize=(7.15, 2.8))
    for ax, trace in zip(axes, ["saturated", "burst"]):
        for policy, label, color, marker in zip(POLICIES, LABELS, COLORS, MARKERS):
            values = [
                [t["campaign_observed_seconds"] for t in groups[(trace, g, policy)]]
                for g in (1, 2, 4)
            ]
            means = np.mean(values, axis=1)
            limits = np.array(
                [means - np.min(values, axis=1), np.max(values, axis=1) - means]
            )
            ax.errorbar(
                [1, 2, 4],
                means,
                yerr=limits,
                marker=marker,
                color=color,
                label=label,
                lw=1.25,
                ms=4,
                capsize=2,
            )
        ax.set(
            title=trace.capitalize() + " arrivals",
            xlabel="GPU count",
            ylabel="Batch completion time (s)",
            xticks=[1, 2, 4],
            ylim=(0, 610),
        )
        ax.grid(alpha=0.18)
    fig.legend(
        *axes[0].get_legend_handles_labels(), loc="lower center", ncol=3, frameon=False
    )
    fig.tight_layout(rect=(0, 0.16, 1, 1))
    save(fig, "measured_scaling")

    fig, axes = plt.subplots(2, 2, figsize=(7.15, 5.05))
    for row_index, trace in enumerate(["saturated", "burst"]):
        for policy, label, color, marker in zip(POLICIES, LABELS, COLORS, MARKERS):
            gains, fairness = [], []
            for g in (1, 2, 4):
                ts = sorted(groups[(trace, g, policy)], key=lambda t: t["repeat"])
                baseline = sorted(groups[(trace, g, "fcfs")], key=lambda t: t["repeat"])
                gains.append(
                    [
                        100
                        * (
                            b["mean_successful_flow_seconds"]
                            - t["mean_successful_flow_seconds"]
                        )
                        / b["mean_successful_flow_seconds"]
                        for t, b in zip(ts, baseline)
                    ]
                )
                fairness.append(
                    [t["inverse_mean_slowdown_jain_successful_only"] for t in ts]
                )
            for ax, values in zip(axes[row_index], [gains, fairness]):
                means = np.mean(values, axis=1)
                limits = np.array(
                    [means - np.min(values, axis=1), np.max(values, axis=1) - means]
                )
                ax.errorbar(
                    [1, 2, 4],
                    means,
                    yerr=limits,
                    marker=marker,
                    color=color,
                    label=label,
                    lw=1.1,
                    ms=4,
                    capsize=2,
                )
                ax.set(xlabel="GPU count", xticks=[1, 2, 4])
                ax.grid(alpha=0.18)
        axes[row_index, 0].set(
            title=trace.capitalize() + ": turnaround", ylabel="Reduction vs FIFO (%)"
        )
        axes[row_index, 0].axhline(0, color="black", lw=0.6)
        axes[row_index, 1].set(
            title=trace.capitalize() + ": owner fairness",
            ylabel="Jain index (inverse slowdown)",
            ylim=(0.85, 1.005),
        )
    fig.legend(
        *axes[0, 0].get_legend_handles_labels(),
        loc="lower center",
        ncol=3,
        frameon=False,
    )
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    save(fig, "measured_tradeoffs")

    rows = data["prediction_observations"]
    fig, axes = plt.subplots(1, 2, figsize=(7.15, 2.65))
    for key, label, color, marker in [
        ("runtime_p50_seconds", "Median estimate", "#0072B2", "o"),
        ("runtime_p90_seconds", "Upper estimate", "#D55E00", "^"),
    ]:
        axes[0].scatter(
            [r["actual_runtime_seconds"] for r in rows],
            [r[key] for r in rows],
            s=23,
            alpha=0.65,
            label=label,
            color=color,
            marker=marker,
        )
    axes[0].plot([35, 65], [35, 65], "--", color="grey", lw=1)
    axes[0].set(
        xlabel="Measured runtime (s)",
        ylabel="Predicted runtime (s)",
        title="Held-out runtime: MAE 0.945 s",
    )
    axes[0].legend(frameon=False, fontsize=7)
    axes[1].scatter(
        [r["actual_memory_gib"] for r in rows],
        [r["memory_p90_gib"] for r in rows],
        s=25,
        alpha=0.65,
        color="#D55E00",
        marker="^",
    )
    axes[1].plot([0, 20], [0, 20], "--", color="grey", lw=1)
    axes[1].set(
        xlabel="Sampled peak memory (GiB)",
        ylabel="Predicted upper memory (GiB)",
        title="Held-out memory: 24/24 covered",
        xlim=(0, 20),
        ylim=(0, 20),
    )
    for ax in axes:
        ax.grid(alpha=0.18)
    fig.tight_layout()
    save(fig, "measured_predictor")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-evidence", action="store_true")
    args = parser.parse_args()
    if args.refresh_evidence:
        extract()
    plot_results(read(EVIDENCE))
    print("Generated three measured-result figures as PDF, PNG and SVG.")
