"""Preflight, checksummed transfer bundle, and bounded sequential GPU profiling."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from experiments.benchmark import validate
from scheduling.live import busy_gpus, discover_gpus, lease
from scheduling.live_store import atomic_json, digest


def cache_inventory(cache):
    if not (cache / "boltz2_conf.ckpt").is_file() or not (cache / "mols").is_dir():
        raise ValueError("cache needs boltz2_conf.ckpt and extracted mols directory")
    files = sorted(p for p in cache.rglob("*") if p.is_file())
    if not any(p.parent.name == "mols" for p in files):
        raise ValueError("empty molecular asset cache")
    return {
        str(p.relative_to(cache)): {"bytes": p.stat().st_size, "sha256": digest(p)} for p in files
    }


def preflight(benchmark, cache, count, output, image=None, expected_inventory=None):
    validate(benchmark)
    gpus = discover_gpus()
    if len(gpus) < count:
        raise ValueError(f"need {count} GPUs; found {len(gpus)}")
    occupied = busy_gpus()
    if occupied:
        raise RuntimeError(f"compute processes already running on GPUs: {sorted(occupied)}")
    output.parent.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(output.parent).free
    if free < 20 * 1024**3:
        raise ValueError("less than 20 GiB free for outputs; provision more storage")
    lock_dir = Path(os.environ.get("HELIXFLOW_LOCK_DIR", f"/tmp/helixflow-gpu-locks-{os.getuid()}"))
    for gpu in gpus[:count]:
        fd = lease(lock_dir / f"{gpu.gpu_id}.lock")
        if fd is None:
            raise RuntimeError(f"GPU lease unavailable: {gpu.gpu_id}")
        os.close(fd)
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import torch; assert torch.cuda.is_available(); "
                "print(torch.__version__,torch.version.cuda,torch.cuda.device_count()); "
                "x=torch.ones(4,device='cuda'); print(x.sum().item())"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assets = cache_inventory(cache)
    if expected_inventory:
        expected = json.loads(expected_inventory.read_text())["model_cache"]
        if expected != assets:
            raise ValueError("transferred model cache differs from the handoff inventory")
    image_info = None
    if image:
        image_info = json.loads(
            subprocess.run(
                ["docker", "image", "inspect", image], check=True, capture_output=True, text=True
            ).stdout
        )[0]
        image_info = {k: image_info[k] for k in ("Id", "RepoDigests", "Architecture", "Os")}
    payload = {
        "schema_version": "1.0",
        "checked_at": time.time(),
        "benchmark": str(benchmark),
        "benchmark_sha256": digest(benchmark / "frozen.json"),
        "gpus": [g.gpu_id for g in gpus],
        "free_disk_bytes": free,
        "torch_cuda_probe": probe.stdout,
        "lock_dir": str(lock_dir),
        "cache": str(cache),
        "cache_assets": assets,
        "image": image_info,
        "nvidia_smi": subprocess.run(
            ["nvidia-smi"], check=True, capture_output=True, text=True
        ).stdout,
    }
    atomic_json(output, payload)
    print(f"Preflight passed for {count} GPUs; cached assets: {len(assets)}")
    return payload


def bundle(benchmark, output, cache=None, source=None):
    """Research transfer archive; MSA redistribution terms remain a release decision."""
    validate(benchmark)
    if output.exists():
        raise ValueError("bundle output already exists")
    base = (
        source or Path(os.environ.get("HELIXFLOW_SOURCE", Path(__file__).resolve().parents[1]))
    ).resolve()
    if not (base / "pyproject.toml").is_file():
        raise ValueError(
            "bundle requires a source checkout; supply --source with the scheduler directory"
        )
    sources = {}
    for folder in ("experiments", "scheduling", "tests", "config", "examples"):
        for path in sorted((base / folder).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                sources[f"multi_gpu_scheduler/{path.relative_to(base)}"] = path
    for name in (
        "pyproject.toml",
        "Dockerfile",
        "Dockerfile.dockerignore",
        "runtime-constraints.txt",
        "compose.yaml",
        "README.md",
        "LIVE_EXECUTION.md",
        "EXPERIMENT_PLAN.md",
        "VM_RUNBOOK.md",
    ):
        sources[f"multi_gpu_scheduler/{name}"] = base / name
    for path in base.glob("*.md"):
        sources[f"multi_gpu_scheduler/{path.name}"] = path
    for path in sorted(benchmark.rglob("*")):
        if path.is_file() and not path.name.endswith(".tmp"):
            sources[f"benchmark/{path.relative_to(benchmark)}"] = path
    for name in ("LICENSE", "local_install/requirements.txt"):
        sources[name] = base.parent / name
    manifest = {
        "schema_version": "1.0",
        "purpose": "private research transfer",
        "benchmark_sha256": digest(benchmark / "frozen.json"),
        "files": {
            name: {"sha256": digest(path), "bytes": path.stat().st_size}
            for name, path in sources.items()
        },
        "model_cache": cache_inventory(cache) if cache else None,
        "release_review": "PDB API data CC0; review alignment database terms before public redistribution. Boltz model terms are separate. Cache bytes and Docker image are transferred separately.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, path in sources.items():
            archive.write(path, name)
        archive.writestr("transfer-manifest.json", json.dumps(manifest, indent=2))
    atomic_json(
        output.with_suffix(".manifest.json"), {"archive_sha256": digest(output), **manifest}
    )
    print(f"Created {output} ({output.stat().st_size} bytes)")


def verify_bundle(path):
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("transfer-manifest.json"))
        import hashlib

        if set(archive.namelist()) != {*manifest["files"], "transfer-manifest.json"}:
            raise ValueError("unexpected files in transfer archive")
        if len(set(archive.namelist())) != len(archive.namelist()):
            raise ValueError("duplicate archive paths")
        for name, entry in manifest["files"].items():
            if Path(name).is_absolute() or ".." in Path(name).parts:
                raise ValueError("unsafe archive path")
            data = archive.read(name)
            if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise ValueError(f"bundle integrity failure: {name}")
    print(f"Verified {len(manifest['files'])} transfer files")


def profile(benchmark, output, cache, *, pilot=True, budget=7200, timeout=1200, repeats=1):
    validate(benchmark)
    from experiments.campaign import code_hashes, versions

    catalog = json.loads((benchmark / "prepared.json").read_text())
    records = catalog["records"]
    if pilot:
        selected = []
        for band in sorted({tuple(r["length_band"]) for r in records}):
            for kind in ("monomer", "protein_ligand"):
                candidates = [
                    r for r in records if tuple(r["length_band"]) == band and r["job_type"] == kind
                ]
                selected.append(min(candidates, key=lambda r: r["job_id"]))
        records = selected
    output.mkdir(parents=True, exist_ok=True)
    signature = {
        "benchmark_sha256": digest(benchmark / "frozen.json"),
        "pilot": pilot,
        "records": [r["job_id"] for r in records],
        "options": catalog["options"],
        "budget_seconds": budget,
        "timeout_seconds": timeout,
        "repeats": repeats,
        "cache": str(cache),
        "code_sha256": code_hashes(),
        "package_versions": versions(),
    }
    index_path = output / "profiling.json"
    index = (
        json.loads(index_path.read_text())
        if index_path.exists()
        else {"signature": signature, "spent_seconds": 0, "attempts": [], "stopped_reason": None}
    )
    if signature != index["signature"]:
        raise ValueError("profiling configuration drift; use a new output directory")
    fd = lease(output / "profiling.lock")
    if fd is None:
        raise RuntimeError("another profiling runner is active")
    try:
        for repeat in range(1, repeats + 1):
            for record in records:
                key = f"{record['job_id']}-r{repeat}"
                previous = next((a for a in index["attempts"] if a["id"] == key), None)
                if previous:
                    if previous["status"] != "SUCCEEDED":
                        index["stopped_reason"] = (
                            "inspect previous failed or interrupted attempt before continuing"
                        )
                        atomic_json(index_path, index)
                        return index
                    continue
                remaining = budget - index["spent_seconds"]
                if remaining <= 1 or busy_gpus():
                    index["stopped_reason"] = "budget exhausted or GPU busy"
                    atomic_json(index_path, index)
                    return index
                result_path = output / f"{key}.json"
                entry = {"id": key, "status": "RUNNING", "started_at": time.time()}
                index["attempts"].append(entry)
                atomic_json(index_path, index)
                started = time.monotonic()
                command = [
                    sys.executable,
                    "-m",
                    "experiments.profile_job",
                    str(benchmark / record["input"]),
                    "--job-id",
                    record["job_id"],
                    "--repeat",
                    str(repeat),
                    "--cache",
                    str(cache),
                    "--output",
                    str(result_path),
                    "--out-dir",
                    str(output / key),
                    "--timeout-seconds",
                    str(min(timeout, remaining)),
                    "--biological-group-id",
                    record["biological_group_id"],
                    "--split",
                    record["split"],
                    "--benchmark-sha256",
                    signature["benchmark_sha256"],
                ]
                for option, value in catalog["options"].items():
                    command += ["--" + option.replace("_", "-"), str(value)]
                with (output / f"{key}.log").open("w") as log:
                    completed = subprocess.run(
                        command, check=False, stdout=log, stderr=subprocess.STDOUT
                    )
                elapsed = time.monotonic() - started
                index["spent_seconds"] += elapsed
                result = json.loads(result_path.read_text()) if result_path.exists() else {}
                entry.update(
                    status=result.get("status", "ENVIRONMENT_FAILURE"),
                    elapsed_seconds=elapsed,
                    profile=str(result_path),
                    return_code=completed.returncode,
                )
                atomic_json(index_path, index)
                print(f"{key}: {entry['status']} ({elapsed:.1f}s)", flush=True)
                if entry["status"] != "SUCCEEDED":
                    index["stopped_reason"] = (
                        "failed attempt; inspect diagnostics before further GPU work"
                    )
                    atomic_json(index_path, index)
                    return index
        index["stopped_reason"] = "all requested profiles complete"
        atomic_json(index_path, index)
        return index
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("preflight", "bundle", "profile"):
        cmd = commands.add_parser(name)
        cmd.add_argument("benchmark", type=Path)
        cmd.add_argument("--output", type=Path, required=True)
        cmd.add_argument("--cache", type=Path, default=Path("/workspace/cache"))
        if name == "preflight":
            cmd.add_argument("--gpus", type=int, default=4)
            cmd.add_argument("--image")
            cmd.add_argument(
                "--inventory", type=Path, help="handoff sidecar containing model-cache hashes"
            )
        elif name == "profile":
            cmd.add_argument(
                "--all", action="store_true", help="all targets; default six-case pilot"
            )
            cmd.add_argument("--budget-seconds", type=float, default=7200)
            cmd.add_argument("--timeout-seconds", type=float, default=1200)
            cmd.add_argument("--repeats", type=int, default=1)
        elif name == "bundle":
            cmd.add_argument(
                "--source",
                type=Path,
                help="scheduler source directory; inferred for source installs and image",
            )
    verify = commands.add_parser("verify-bundle")
    verify.add_argument("archive", type=Path)
    args = parser.parse_args()
    if args.command == "verify-bundle":
        verify_bundle(args.archive)
    elif args.command == "preflight":
        if args.gpus < 1:
            parser.error("GPU count must be positive")
        preflight(
            args.benchmark.resolve(),
            args.cache.resolve(),
            args.gpus,
            args.output.resolve(),
            args.image,
            args.inventory,
        )
    elif args.command == "bundle":
        bundle(args.benchmark.resolve(), args.output.resolve(), args.cache.resolve(), args.source)
    else:
        from scheduling.live_store import positive

        if args.repeats < 1:
            parser.error("repeats must be positive")
        result = profile(
            args.benchmark.resolve(),
            args.output.resolve(),
            args.cache.resolve(),
            pilot=not args.all,
            budget=positive(args.budget_seconds, "budget"),
            timeout=positive(args.timeout_seconds, "timeout"),
            repeats=args.repeats,
        )
        print(result["stopped_reason"])
        if result["stopped_reason"] != "all requested profiles complete":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
