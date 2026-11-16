"""Local durable campaign store. Trusted single-host use; not a network service."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path

import yaml

from .features import extract_features
from .models import RuntimePrediction

TERMINAL = {"SUCCEEDED", "FAILED", "UNSCHEDULABLE"}
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}$")


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    import os

    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def connect(root: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(root / "queue.sqlite3", timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    return connection


def initialize(root: Path, settings: dict) -> None:
    root.mkdir(parents=True, exist_ok=False)
    (root / "inputs").mkdir()
    (root / "attempts").mkdir()
    with connect(root) as db:
        db.executescript("""
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE jobs (
                job_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
                submitted_at REAL NOT NULL, ready_at REAL NOT NULL,
                status TEXT NOT NULL, spec TEXT NOT NULL, attempt_count INTEGER NOT NULL DEFAULT 0,
                reason TEXT, published_attempt TEXT
            );
            CREATE TABLE attempts (
                attempt_id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(job_id),
                ordinal INTEGER NOT NULL, gpu_id TEXT NOT NULL, status TEXT NOT NULL,
                claimed_at REAL NOT NULL, finished_at REAL, reserved_seconds REAL NOT NULL,
                receipt TEXT, UNIQUE(job_id, ordinal)
            );
        """)
        db.execute("INSERT INTO metadata VALUES ('settings', ?)", (json.dumps(settings),))


def settings_for(db: sqlite3.Connection) -> dict:
    return json.loads(db.execute("SELECT value FROM metadata WHERE key='settings'").fetchone()[0])


def positive(value: object, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return number


def snapshot_input(source: Path, destination: Path) -> tuple[Path, dict[str, str]]:
    """Support protein/ligand YAML with explicit empty or validated local A3M MSAs.

    External templates/constraints and molecule files are intentionally not yet
    supported: do not let undocumented dependencies enter a controlled campaign.
    """
    document = yaml.safe_load(source.read_text())
    if not isinstance(document, dict) or document.get("version") != 1:
        raise ValueError("live inputs must be Boltz version-1 YAML")
    if set(document) - {"version", "sequences", "properties"}:
        raise ValueError("unsupported YAML fields; templates/constraints need explicit staging support")
    entries = document.get("sequences")
    if not isinstance(entries, list) or not entries:
        raise ValueError("input needs a nonempty sequences list")
    files = {}
    seen_ids = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or len(entry) != 1:
            raise ValueError("each sequence entry must contain exactly one molecule")
        kind, molecule = next(iter(entry.items()))
        if kind not in {"protein", "ligand"} or not isinstance(molecule, dict):
            raise ValueError("live release supports protein and ligand YAML entries")
        allowed = {"id", "sequence", "msa"} if kind == "protein" else {"id", "smiles", "ccd"}
        if set(molecule) - allowed:
            raise ValueError(f"unsupported {kind} input fields")
        ids = molecule.get("id")
        ids = ids if isinstance(ids, list) else [ids]
        if not ids or any(not isinstance(i, str) or not i for i in ids):
            raise ValueError("each molecule needs nonempty chain ids")
        if len(set(ids)) != len(ids) or seen_ids.intersection(ids):
            raise ValueError("chain ids must be unique")
        seen_ids.update(ids)
        if kind == "ligand":
            if bool(molecule.get("smiles")) == bool(molecule.get("ccd")):
                raise ValueError("ligands require exactly one of smiles or ccd")
            continue
        sequence = molecule.get("sequence", "")
        if not isinstance(sequence, str) or not re.fullmatch(r"[A-Z]+", sequence):
            raise ValueError("protein sequences must be nonempty uppercase letters")
        msa = molecule.get("msa")
        if msa == "empty":
            continue
        if not isinstance(msa, str) or not msa:
            raise ValueError("supply a local A3M or explicitly set msa: empty; no automatic MSA calls")
        msa_path = (source.parent / msa).resolve()
        if msa_path.suffix.lower() != ".a3m":
            raise ValueError("only A3M MSAs are supported in the live release")
        text = msa_path.read_text()
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines or not lines[0].startswith(">"):
            raise ValueError("A3M must start with a query header")
        query = []
        for line in lines[1:]:
            if line.startswith(">"):
                break
            query.append(line)
        aligned_query = re.sub(r"[a-z.-]", "", "".join(query))
        if aligned_query != sequence:
            raise ValueError(f"MSA query does not match protein sequence for chain {ids}")
        target = destination / f"msa-{index}.a3m"
        files[target] = text
        molecule["msa"] = str(target)
    destination.mkdir(parents=True, exist_ok=False)
    for target, text in files.items():
        target.write_text(text)
    target = destination / "input.yaml"
    target.write_text(yaml.safe_dump(document, sort_keys=False))
    hashes = {str(path): digest(path) for path in [target, *files]}
    return target, hashes


def submit(root: Path, manifest_path: Path, model: Path | None = None) -> int:
    manifest = json.loads(manifest_path.read_text())
    entries = manifest.get("jobs")
    if not isinstance(entries, list) or not entries:
        raise ValueError("manifest needs a nonempty jobs list")
    predictor = None
    if model is not None:
        from .predictor import PredictorBundle
        predictor = PredictorBundle.load(model)  # Trusted local pickle only.
    with connect(root) as db:
        settings = settings_for(db)
        if predictor is not None:
            provenance = getattr(predictor, "provenance", None) or {}
            trained_hardware = provenance.get("hardware", [])
            if trained_hardware and settings.get("hardware_label") not in trained_hardware:
                raise ValueError("predictor hardware differs from campaign hardware; profile and fit on target GPUs")
        # Also serializes concurrent submissions of the same job id.
        db.execute("BEGIN IMMEDIATE")
        rows = []
        submitted = time.time()
        for entry in entries:
            job_id, owner = entry["job_id"], entry["owner_id"]
            if not IDENTIFIER.fullmatch(job_id) or not IDENTIFIER.fullmatch(owner):
                raise ValueError("job/owner ids must be safe identifiers up to 101 characters")
            if db.execute("SELECT 1 FROM jobs WHERE job_id=?", (job_id,)).fetchone():
                raise ValueError(f"job already exists: {job_id}")
            if any(row[0] == job_id for row in rows):
                raise ValueError(f"duplicate job in manifest: {job_id}")
            source = (manifest_path.parent / entry["input"]).resolve()
            # Validate options before staging; unsupported knobs are not silently ignored.
            options = entry.get("options", {})
            if set(options) - {"recycling_steps", "sampling_steps", "diffusion_samples"}:
                raise ValueError("unsupported prediction option")
            options = {key: options.get(key, default) for key, default in (
                ("recycling_steps", 3), ("sampling_steps", 200), ("diffusion_samples", 1)
            )}
            if any(type(v) is not int or v <= 0 for v in options.values()):
                raise ValueError("inference options must be positive integers")
            delay = float(entry.get("arrival_offset_seconds", 0))
            if not math.isfinite(delay) or delay < 0:
                raise ValueError("arrival offset must be finite and nonnegative")
            attempts = entry.get("max_attempts", 1)
            if type(attempts) is not int or not 1 <= attempts <= 10:
                raise ValueError("max_attempts must be an integer in [1, 10]")
            if "mock" in entry and settings["backend"] != "mock":
                raise ValueError("mock controls are forbidden in a real Boltz campaign")
            mock = entry.get("mock", {})
            if not isinstance(mock, dict) or set(mock) - {
                "duration_seconds", "fail_attempts", "missing_artifacts"
            }:
                raise ValueError("unsupported mock controls")
            if mock:
                positive(mock.get("duration_seconds", .05), "mock duration")
                failures = mock.get("fail_attempts", 0)
                if type(failures) is not int or failures < 0:
                    raise ValueError("mock fail_attempts must be a nonnegative integer")
            timeout = positive(entry.get("timeout_seconds", 3600), "timeout_seconds")
            if "ccd_atom_counts" in entry and settings["backend"] != "mock":
                raise ValueError("supplied CCD atom counts are only allowed for mock execution")
            features = extract_features(
                source, options=options, cache=Path(settings["cache"]),
                ccd_atom_counts=entry.get("ccd_atom_counts"),
            )
            prediction = predictor.predict(features) if predictor else RuntimePrediction(
                **entry["prediction"]
            )
            # Unique directories also preserve evidence from a rejected/rolled-back submission.
            import uuid
            staged, hashes = snapshot_input(source, root / "inputs" / f"{job_id}-{uuid.uuid4().hex}")
            spec = {
                "biological_group_id": entry.get("biological_group_id", ""),
                "split": entry.get("split", ""),
                "benchmark_sha256": entry.get("benchmark_sha256", ""),
                "input": str(staged), "input_hashes": hashes,
                "source_sha256": digest(source), "options": options,
                "features": asdict(features), "prediction": asdict(prediction),
                "prediction_source": (
                    f"trusted-model-sha256:{digest(model)}" if model
                    else entry.get("prediction_source", "manual-unvalidated")
                ),
                "timeout_seconds": timeout, "max_attempts": attempts,
                "mock": mock,
            }
            rows.append((job_id, owner, submitted, submitted + delay, "QUEUED", json.dumps(spec)))
        db.executemany(
            "INSERT INTO jobs(job_id,owner_id,submitted_at,ready_at,status,spec) VALUES(?,?,?,?,?,?)",
            rows,
        )
    return len(rows)
