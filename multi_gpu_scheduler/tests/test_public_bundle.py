"""A public projection must never relax scientific input integrity checks."""
import json

import pytest
from test_experiment_workflow import fixture_benchmark

from experiments.benchmark import revise_ligands, validate
from experiments.public_bundle import DOCUMENTATION, MANIFEST, validate_public_inventory
from scheduling.live_store import atomic_json, digest


def public_fixture(tmp_path):
    root = fixture_benchmark(tmp_path)
    frozen = json.loads((root / "frozen.json").read_text())
    # Add a synthetic cached source record to the original inventory before projection.
    cached = root / "source-cache/source.json"
    cached.write_text('{"synthetic": true}')
    frozen["sha256"]["source-cache/source.json"] = digest(cached)
    atomic_json(root / "frozen.json", frozen)
    original_hash = digest(root / "frozen.json")
    cached.unlink()
    for name in DOCUMENTATION:
        (root / name).write_text("synthetic packaging fixture\n")
    manifest = {
        "schema_version": "1.0", "kind": "helixflow-public-workload",
        "original_frozen_sha256": original_hash,
        "omitted_source_cache": {"source-cache/source.json": frozen["sha256"]["source-cache/source.json"]},
        "files": {p.relative_to(root).as_posix(): {"bytes": p.stat().st_size, "sha256": digest(p)}
                  for p in root.rglob("*") if p.is_file()},
    }
    atomic_json(root / MANIFEST, manifest)
    return root, manifest, original_hash


def test_public_projection_preserves_original_fingerprint(tmp_path):
    root, _, fingerprint = public_fixture(tmp_path)
    assert len(validate_public_inventory(root)) == 1
    frozen = validate(root)
    assert "source-cache/source.json" in frozen["sha256"]
    assert digest(root / "frozen.json") == fingerprint


def test_full_workload_still_requires_source_cache(tmp_path):
    root, _, _ = public_fixture(tmp_path)
    (root / MANIFEST).unlink()
    with pytest.raises(FileNotFoundError):
        validate(root)


@pytest.mark.parametrize("name", ["inputs/job-0.yaml", "msas/job-0.a3m", "prepared.json",
                                  "msas/job-0.provenance.json", "DATA_NOTICE.md"])
def test_public_payload_tampering_rejected(tmp_path, name):
    root, _, _ = public_fixture(tmp_path)
    with (root / name).open("a") as stream:
        stream.write("changed")
    with pytest.raises(ValueError, match="changed"):
        validate(root)


def test_cannot_declare_an_msa_omitted(tmp_path):
    root, manifest, _ = public_fixture(tmp_path)
    manifest["omitted_source_cache"]["msas/job-0.a3m"] = manifest["files"]["msas/job-0.a3m"]["sha256"]
    atomic_json(root / MANIFEST, manifest)
    with pytest.raises(ValueError, match="omissions"):
        validate(root)


def test_updating_release_hash_cannot_mask_changed_input(tmp_path):
    root, manifest, _ = public_fixture(tmp_path)
    path = root / "inputs/job-0.yaml"
    path.write_text("changed")
    manifest["files"]["inputs/job-0.yaml"] = {"bytes": path.stat().st_size, "sha256": digest(path)}
    atomic_json(root / MANIFEST, manifest)
    with pytest.raises(ValueError, match="original benchmark asset changed"):
        validate(root)


@pytest.mark.parametrize("name", ["extra.txt", "source-cache/unreviewed.json"])
def test_unexpected_files_rejected(tmp_path, name):
    root, _, _ = public_fixture(tmp_path)
    (root / name).write_text("unexpected")
    with pytest.raises(ValueError, match="unexpected"):
        validate(root)


def test_missing_file_and_symlink_rejected(tmp_path):
    root, _, _ = public_fixture(tmp_path)
    path = root / "msas/job-0.a3m"
    path.unlink()
    with pytest.raises(ValueError, match="missing"):
        validate(root)
    path.symlink_to(root / "msas/job-1.a3m")
    with pytest.raises(ValueError, match="symlinks"):
        validate(root)


def test_fingerprint_change_rejected(tmp_path):
    root, _, _ = public_fixture(tmp_path)
    with (root / "frozen.json").open("a") as stream:
        stream.write("\n")
    with pytest.raises(ValueError, match="fingerprint"):
        validate(root)


def test_revision_rejects_incomplete_source_before_writing(tmp_path):
    root, _, _ = public_fixture(tmp_path)
    destination = tmp_path / "revision"
    with pytest.raises(ValueError, match="complete original workload"):
        revise_ligands(root, destination, ["HEM"], tmp_path / "cache")
    assert not destination.exists()
