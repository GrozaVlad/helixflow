"""Plan and resume matched, sequential scheduling trials on one GPU host."""

from __future__ import annotations

import argparse
import copy
import csv
import importlib.metadata
import json
import os
import random
import signal
import statistics
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

from experiments.benchmark import validate
from experiments.compare_live import compare
from experiments.live_scheduler import LIVE_POLICIES, report
from scheduling.features import extract_features
from scheduling.live import busy_gpus, discover_gpus, lease
from scheduling.live_store import atomic_json, connect, digest, settings_for, submit
from scheduling.models import GPUDevice
from scheduling.predictor import PredictorBundle

DEFAULT_VARIANTS = [*LIVE_POLICIES, "uaf_no_service"]


def code_hashes():
    base = Path(__file__).resolve().parents[1]
    return {
        str(p.relative_to(base)): digest(p)
        for directory in ("scheduling", "experiments")
        for p in sorted((base / directory).glob("*.py"))
    }


def versions():
    result = {}
    for name in ("boltz", "torch", "numpy", "scikit-learn", "PyYAML"):
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = None
    return result


def read_json(path):
    return json.loads(path.read_text())


def resolved(base, value):
    return (base / value).resolve()


def model_for(path):
    model = PredictorBundle.load(path)
    provenance = getattr(model, "provenance", None) or {}
    if provenance.get("grouping") != "explicit-biological" or not provenance.get("hardware"):
        raise ValueError(
            "performance campaigns require a model fitted with explicit biological splits and hardware"
        )
    return model


def prepare_jobs(config, base):
    benchmark = resolved(base, config["benchmark"])
    validate(benchmark)
    catalog = read_json(benchmark / "prepared.json")
    fingerprint = digest(benchmark / "frozen.json")
    mock = config.get("backend", "boltz") == "mock"
    model_path = resolved(base, config["model"]) if not mock else None
    model = model_for(model_path) if model_path else None
    records = [r for r in catalog["records"] if r["split"] == "test"]
    if not records:
        raise ValueError("benchmark has no held-out test targets")
    if model:
        if model.provenance.get("benchmark_sha256") != [fingerprint]:
            raise ValueError("predictor was fitted against another benchmark version")
        trained = set(model.provenance["training_groups"]) | set(
            model.provenance["calibration_groups"]
        )
        if trained.intersection(r["biological_group_id"] for r in records):
            raise ValueError("test biological groups overlap model fitting/calibration")
    jobs = []
    for index, record in enumerate(sorted(records, key=lambda r: r["job_id"])):
        source = benchmark / record["input"]
        ligand = record.get("ligand")
        mock_counts = {ligand["ccd"]: ligand["heavy_atoms"]} if ligand else {}
        features = extract_features(
            source, options=catalog["options"],
            cache=resolved(base, config.get("cache", "/workspace/cache")),
            ccd_atom_counts=mock_counts if mock else None,
        )
        prediction = (
            asdict(model.predict(features))
            if model
            else {
                "runtime_p50_seconds": 1,
                "runtime_p90_seconds": 2,
                "memory_p90_gib": 2,
            }
        )
        entry = {
            "job_id": record["job_id"],
            "owner_id": f"researcher-{index % 4}",
            "input": str(source),
            "options": catalog["options"],
            "prediction": prediction,
            "prediction_source": f"trusted-model-sha256:{digest(model_path)}"
            if model
            else "mock-only",
            "biological_group_id": record["biological_group_id"],
            "split": "test",
            "benchmark_sha256": fingerprint,
            "max_attempts": 1,
            "timeout_seconds": config.get("timeout_seconds", 3600),
        }
        if mock:
            entry["ccd_atom_counts"] = mock_counts
            entry["mock"] = {"duration_seconds": config.get("mock_duration_seconds", 0.05)}
        jobs.append(entry)
    return jobs, benchmark, model_path


def plan(config_path, root):
    config_path, root = config_path.resolve(), root.resolve()
    config = read_json(config_path)
    if config.get("schema_version") != "1.0" or config.get("backend", "boltz") not in {
        "boltz",
        "mock",
    }:
        raise ValueError("invalid schema_version or backend")
    jobs, benchmark, model = prepare_jobs(config, config_path.parent)
    gpu_counts = config.get("gpu_counts", [1, 2, 4])
    variants = config.get("variants", DEFAULT_VARIANTS)
    traces = config.get("traces", ["saturated", "burst"])
    repeats = config.get("repetitions", 3)
    if (
        not gpu_counts
        or len(set(gpu_counts)) != len(gpu_counts)
        or any(type(n) is not int or n < 1 for n in gpu_counts)
        or not variants
        or len(set(variants)) != len(variants)
        or set(variants) - set(DEFAULT_VARIANTS)
        or not traces
        or len(set(traces)) != len(traces)
        or set(traces) - {"saturated", "burst"}
        or type(repeats) is not int
        or repeats < 1
    ):
        raise ValueError("invalid GPU counts, variants, traces, or repetition count")
    seed = config.get("seed", 42)
    gap = float(config.get("burst_gap_seconds", 60))
    if not 0 <= gap < float("inf"):
        raise ValueError("burst gap must be finite and nonnegative")
    root.mkdir(parents=True, exist_ok=False)
    (root / "manifests").mkdir()
    manifests, trials = {}, []
    for repeat in range(repeats):
        ordered = copy.deepcopy(jobs)
        random.Random(seed + repeat).shuffle(ordered)
        for trace in traces:
            entries = copy.deepcopy(ordered)
            for i, entry in enumerate(entries):
                # All saturated jobs are ready by first dispatch. A 1ms logical
                # tie break preserves the seeded order in FIFO rather than job-id order.
                entry["arrival_offset_seconds"] = (
                    i * 0.001 if trace == "saturated" else (i // 4) * gap + (i % 4) * 0.001
                )
            key = f"{trace}-r{repeat + 1}"
            path = root / "manifests" / f"{key}.json"
            atomic_json(path, {"jobs": entries})
            manifests[str(path.relative_to(root))] = digest(path)
            for count in gpu_counts:
                for variant in variants:
                    trials.append(
                        {
                            "id": f"{key}-g{count}-{variant}",
                            "trace": trace,
                            "repeat": repeat + 1,
                            "gpus": count,
                            "variant": variant,
                            "manifest": str(path.relative_to(root)),
                        }
                    )
    random.Random(seed).shuffle(trials)
    frozen = {
        "schema_version": "1.0",
        "config": config,
        "benchmark": str(benchmark),
        "benchmark_sha256": digest(benchmark / "frozen.json"),
        "model": str(model) if model else None,
        "model_sha256": digest(model) if model else None,
        "cache": str(resolved(config_path.parent, config.get("cache", "/workspace/cache"))),
        "code_sha256": code_hashes(),
        "package_versions": versions(),
        "manifests": manifests,
        "trials": trials,
    }
    atomic_json(root / "plan.json", frozen)
    atomic_json(
        root / "index.json",
        {
            "plan_sha256": digest(root / "plan.json"),
            "trials": {t["id"]: {"state": "PLANNED"} for t in trials},
        },
    )
    print(f"Planned {len(trials)} trials, {len(jobs)} held-out jobs/trial: {root}")
    return frozen


def check_plan(root):
    frozen = read_json(root / "plan.json")
    if read_json(root / "index.json")["plan_sha256"] != digest(root / "plan.json"):
        raise ValueError("campaign plan changed after initialization")
    if code_hashes() != frozen["code_sha256"] or versions() != frozen["package_versions"]:
        raise ValueError("code or Python environment changed after planning; create a new campaign")
    benchmark = Path(frozen["benchmark"])
    validate(benchmark)
    if digest(benchmark / "frozen.json") != frozen["benchmark_sha256"]:
        raise ValueError("benchmark fingerprint changed")
    if frozen["model"] and digest(Path(frozen["model"])) != frozen["model_sha256"]:
        raise ValueError("predictor changed")
    for name, expected in frozen["manifests"].items():
        if digest(root / name) != expected:
            raise ValueError("planned manifest changed")
    return frozen


def run(root, *, limit=None):
    root = root.resolve()
    lock = lease(root / "runner.lock")
    if lock is None:
        raise RuntimeError("another runner owns this campaign")
    child, stopping = None, False

    def stop(_sig, _frame):
        nonlocal stopping
        stopping = True
        if child and child.poll() is None:
            child.send_signal(signal.SIGTERM)

    handlers = {s: signal.signal(s, stop) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        frozen = check_plan(root)
        config = frozen["config"]
        mock = config.get("backend", "boltz") == "mock"
        devices = (
            [GPUDevice(f"mock-{i}", 16) for i in range(max(t["gpus"] for t in frozen["trials"]))]
            if mock
            else discover_gpus()
        )
        if config.get("gpu_ids"):
            by_id = {g.gpu_id: g for g in devices}
            devices = [by_id[key] for key in config["gpu_ids"]]
        if len(devices) < max(t["gpus"] for t in frozen["trials"]):
            raise ValueError("insufficient GPUs for the planned matrix")
        if not mock:
            from experiments.vm_handoff import cache_inventory

            inventory = cache_inventory(Path(frozen["cache"]))
            cache_path = root / "cache-inventory.json"
            if cache_path.exists() and read_json(cache_path) != inventory:
                raise ValueError("model asset cache changed between trials")
            atomic_json(cache_path, inventory)
        index = read_json(root / "index.json")
        completed = 0
        for trial in frozen["trials"]:
            if stopping or (limit is not None and completed >= limit):
                break
            state = index["trials"][trial["id"]]
            folder = root / "trials" / trial["id"]
            if state["state"] == "COMPLETE":
                previous = folder / "report" / "report.json"
                if digest(previous) != state["report_sha256"]:
                    raise ValueError("completed trial report changed")
                continue
            if not mock and busy_gpus() and not (folder / "queue.sqlite3").exists():
                # A resumed trial may have surviving workers; the coordinator reconciles those.
                raise RuntimeError("GPU compute activity detected before a new trial")
            policy = "uaf_sjf" if trial["variant"] == "uaf_no_service" else trial["variant"]
            if not folder.exists():
                command = [
                    sys.executable,
                    "-m",
                    "experiments.live_scheduler",
                    "init",
                    str(folder),
                    "--policy",
                    policy,
                    "--cache",
                    frozen["cache"],
                    "--lock-dir",
                    os.environ.get("HELIXFLOW_LOCK_DIR", f"/tmp/helixflow-gpu-locks-{os.getuid()}"),
                    "--fairness-weight",
                    "0" if trial["variant"] == "uaf_no_service" else ".25",
                ]
                if mock:
                    command += ["--mock", "--mock-gpus", str(trial["gpus"])]
                else:
                    command += ["--gpu-ids", ",".join(g.gpu_id for g in devices[: trial["gpus"]])]
                subprocess.run(command, check=True)
            with connect(folder) as db:
                queued = db.execute("SELECT count(*) FROM jobs").fetchone()[0]
                settings = settings_for(db)
                if not queued and not mock:
                    settings["cache_sha256"] = digest(root / "cache-inventory.json")
                    db.execute(
                        "UPDATE metadata SET value=? WHERE key='settings'", (json.dumps(settings),)
                    )
                if settings["policy"] != policy or len(settings["gpus"]) != trial["gpus"]:
                    raise ValueError("existing trial configuration differs from plan")
            if not queued:
                submit(
                    folder,
                    root / trial["manifest"],
                    Path(frozen["model"]) if frozen["model"] else None,
                )
            state.update(state="RUNNING", started_at=time.time())
            atomic_json(root / "index.json", index)
            child = subprocess.Popen(
                [sys.executable, "-m", "experiments.live_scheduler", "run", str(folder)]
            )
            child.wait()
            if child.returncode:
                raise RuntimeError(
                    f"trial coordinator exited with code {child.returncode}: {trial['id']}"
                )
            payload = report(folder, folder / "report")
            if payload["metrics"]["all_terminal"]:
                state.update(
                    state="COMPLETE", report_sha256=digest(folder / "report" / "report.json")
                )
                completed += 1
            else:
                state["state"] = "INTERRUPTED"
            atomic_json(root / "index.json", index)
            child = None
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
        os.close(lock)


def summarize(root, output):
    frozen = read_json(root / "plan.json")
    index = read_json(root / "index.json")
    mock = frozen["config"].get("backend", "boltz") == "mock"
    cohorts, rows, owner_rows = {}, [], []
    for trial in frozen["trials"]:
        if index["trials"][trial["id"]]["state"] != "COMPLETE":
            continue
        path = root / "trials" / trial["id"] / "report" / "report.json"
        if digest(path) != index["trials"][trial["id"]]["report_sha256"]:
            raise ValueError("completed trial report changed")
        cohorts.setdefault((trial["trace"], trial["repeat"]), []).append(path)
        row = compare([path], allow_mock=mock)[0]
        row.update(
            trial_id=trial["id"],
            trace=trial["trace"],
            repeat=trial["repeat"],
            variant=trial["variant"],
        )
        rows.append(row)
        payload = read_json(path)
        for owner in sorted({j["owner_id"] for j in payload["jobs"]}):
            jobs = [j for j in payload["jobs"] if j["owner_id"] == owner]
            ids = {j["job_id"] for j in jobs}
            service = sum(
                (a["receipt"] or {}).get("runtime_seconds") or 0
                for a in payload["attempts"]
                if a["job_id"] in ids
            )
            owner_rows.append(
                {
                    "trial_id": trial["id"],
                    "owner_id": owner,
                    "accepted": len(jobs),
                    "succeeded": sum(j["status"] == "SUCCEEDED" for j in jobs),
                    "measured_service_seconds": service,
                    "mean_successful_flow_seconds": payload["metrics"][
                        "mean_successful_flow_by_owner"
                    ].get(owner),
                }
            )
    for paths in cohorts.values():
        compare(paths, allow_mock=mock)
    output.mkdir(parents=True, exist_ok=True)
    for name, entries in (("trials", rows), ("owners", owner_rows)):
        if entries:
            with (output / f"{name}.csv").open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(entries[0]))
                writer.writeheader()
                writer.writerows(entries)
    atomic_json(
        output / "summary.json",
        {
            "evidence_type": "mock_worker_functional_test" if mock else "live_boltz_execution",
            "planned_trials": len(frozen["trials"]),
            "completed_trials": len(rows),
            "trials": rows,
            "aggregation_unit": "one trial; biological targets and repetitions are not independent samples",
        },
    )
    if rows:
        plots(rows, output, mock)
    return rows


def plots(rows, output, mock):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    metrics = [
        ("successful_jobs_per_hour", "Successful jobs/hour"),
        ("mean_initial_wait_seconds", "Mean initial wait (s)"),
        ("mean_successful_flow_seconds", "Mean successful flow (s)"),
        ("worker_occupancy_fraction", "Worker occupancy"),
    ]
    for trace in sorted({r["trace"] for r in rows}):
        figure, axes = plt.subplots(2, 2, figsize=(11, 7), layout="constrained")
        for ax, (metric, label) in zip(axes.flat, metrics, strict=True):
            for variant in sorted({r["variant"] for r in rows}):
                subset = [
                    r
                    for r in rows
                    if r["trace"] == trace and r["variant"] == variant and r[metric] is not None
                ]
                counts = sorted({r["gpus"] for r in subset})
                means = [
                    statistics.mean(r[metric] for r in subset if r["gpus"] == n) for n in counts
                ]
                ax.plot(counts, means, marker="o", label=variant)
                ax.scatter(
                    [r["gpus"] for r in subset], [r[metric] for r in subset], alpha=0.35, s=15
                )
            ax.set(xlabel="GPU count", ylabel=label, xticks=sorted({r["gpus"] for r in rows}))
            ax.grid(alpha=0.2)
        axes.flat[0].legend(fontsize=7)
        figure.suptitle(
            f"{'MOCK FUNCTIONAL TEST — ' if mock else ''}{trace}: lines are repetition means; dots are trials"
        )
        figure.savefig(output / f"{trace}.png", dpi=160)
        figure.savefig(output / f"{trace}.svg")
        plt.close(figure)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    planning = commands.add_parser("plan")
    planning.add_argument("config", type=Path)
    planning.add_argument("--output", required=True, type=Path)
    for name in ("run", "status", "report"):
        command = commands.add_parser(name)
        command.add_argument("root", type=Path)
        if name == "run":
            command.add_argument("--limit", type=int)
        if name == "report":
            command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "plan":
        plan(args.config, args.output)
    elif args.command == "run":
        if args.limit is not None and args.limit < 1:
            parser.error("limit must be positive")
        run(args.root, limit=args.limit)
    elif args.command == "status":
        states = read_json(args.root / "index.json")["trials"].values()
        print(
            json.dumps(
                {
                    key: sum(s["state"] == key for s in states)
                    for key in ("PLANNED", "RUNNING", "INTERRUPTED", "COMPLETE")
                },
                indent=2,
            )
        )
    else:
        summarize(args.root.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
