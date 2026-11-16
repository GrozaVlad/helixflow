"""Acceptance checks for evidence integrity, leakage, and campaign resumption."""

import io
import json
import random
import tarfile
import zipfile
from dataclasses import replace

import pytest
import yaml

from experiments.benchmark import (
    alignment_blocks,
    freeze,
    group_and_split,
    msa,
    revise_ligands,
    validate,
    validate_a3m,
)
from experiments.campaign import check_plan, plan, run, summarize
from experiments.vm_handoff import bundle, profile, verify_bundle
from scheduling.live_store import atomic_json, digest
from scheduling.models import JobFeatures
from scheduling.predictor import TrainingObservation, train_predictor


def fixture_benchmark(tmp_path):
    root = tmp_path / "benchmark"
    (root / "inputs").mkdir(parents=True)
    (root / "msas").mkdir()
    (root / "source-cache").mkdir()
    records = []
    for i in range(60):
        sequence = "A" * (100 + i)
        source, alignment = f"inputs/job-{i}.yaml", f"msas/job-{i}.a3m"
        (root / source).write_text(
            yaml.safe_dump(
                {
                    "version": 1,
                    "sequences": [
                        {"protein": {"id": "A", "sequence": sequence, "msa": f"../{alignment}"}}
                    ],
                }
            )
        )
        (root / alignment).write_text(f">query\n{sequence}\n>hit\nC{sequence[1:]}\n")
        atomic_json((root / alignment).with_suffix(".provenance.json"), {"synthetic_fixture": True})
        records.append(
            {
                "job_id": f"job-{i}",
                "input": source,
                "msa": alignment,
                "sequence": sequence,
                "biological_group_id": f"group-{i}",
                "split": "train" if i < 36 else "calibration" if i < 48 else "test",
            }
        )
    catalog = {
        "records": records,
        "options": {"recycling_steps": 1, "sampling_steps": 10, "diffusion_samples": 1},
        "public_sequences_only": False,
    }
    atomic_json(root / "catalog.json", catalog)
    atomic_json(root / "prepared.json", catalog)
    freeze(root)
    return root


def config_file(tmp_path, benchmark, **overrides):
    config = {
        "schema_version": "1.0",
        "backend": "mock",
        "benchmark": str(benchmark),
        "gpu_counts": [1, 2, 4],
        "variants": ["fcfs", "uaf_no_service"],
        "traces": ["saturated"],
        "repetitions": 1,
        "mock_duration_seconds": 0.02,
    }
    config.update(overrides)
    path = tmp_path / "config.json"
    atomic_json(path, config)
    return path


def test_benchmark_hashes_partitions_and_msa_integrity(tmp_path):
    root = fixture_benchmark(tmp_path)
    validate(root)
    with pytest.raises(ValueError, match="public-source"):
        msa(root, 1)
    (root / "msas/job-0.a3m").write_text(">query\nWRONG\n")
    with pytest.raises(ValueError, match="changed"):
        validate(root)
    with pytest.raises(ValueError, match="query"):
        validate_a3m(">query\nAAA\n>hit\nCAA\n", "BBB")
    with pytest.raises(ValueError, match="widths"):
        validate_a3m(">query\nAAA\n>hit\nAA\n", "AAA")


def test_ligand_revision_retains_original_targets_groups_and_msas(tmp_path, monkeypatch):
    from scheduling import features

    root = fixture_benchmark(tmp_path)
    # Construct a fresh frozen fixture, not an in-place revision of existing evidence.
    prepared = json.loads((root / "prepared.json").read_text())
    prepared["records"][0]["ligand"] = {"ccd": "HEM", "smiles": "CC", "heavy_atoms": 43}
    document = yaml.safe_load((root / "inputs/job-0.yaml").read_text())
    document["sequences"].append({"ligand": {"id": "B", "smiles": "CC"}})
    (root / "inputs/job-0.yaml").write_text(yaml.safe_dump(document))
    atomic_json(root / "prepared.json", prepared)
    # Refresh the synthetic fixture inventory directly before treating it as frozen.
    frozen = json.loads((root / "frozen.json").read_text())
    for relative in frozen["sha256"]:
        frozen["sha256"][relative] = digest(root / relative)
    atomic_json(root / "frozen.json", frozen)
    original = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    cache = tmp_path / "cache"
    (cache / "mols").mkdir(parents=True)
    (cache / "mols/HEM.pkl").write_bytes(b"trusted fixture")
    monkeypatch.setattr(features, "cached_ccd_heavy_atoms", lambda code, cache: 43)
    output = tmp_path / "revision"
    revise_ligands(root, output, ["HEM"], cache)
    validate(root)
    validate(output)
    assert all((root / p).read_bytes() == data for p, data in original.items())
    revised = json.loads((output / "prepared.json").read_text())
    assert [r["job_id"] for r in revised["records"]] == [r["job_id"] for r in prepared["records"]]
    assert [(r["biological_group_id"], r["split"]) for r in revised["records"]] == [
        (r["biological_group_id"], r["split"]) for r in prepared["records"]
    ]
    assert all((output / r["msa"]).read_bytes() == (root / r["msa"]).read_bytes() for r in revised["records"])
    assert yaml.safe_load((output / "inputs/job-0.yaml").read_text())["sequences"][-1] == {
        "ligand": {"id": "B", "ccd": "HEM"}
    }
    assert revised["revision"]["source_benchmark_sha256"] == digest(root / "frozen.json")
    with pytest.raises(ValueError, match="already exists"):
        revise_ligands(root, output, ["HEM"], cache)
    with pytest.raises(ValueError, match="source catalog"):
        revise_ligands(root, tmp_path / "missing", ["UNKNOWN"], cache)


def test_related_targets_share_a_partition():
    rng = random.Random(7)
    records = [
        {
            "job_id": f"job-{i}",
            "sequence": "".join(rng.choices("ACDEFGHIKLMNPQRSTVWY", k=150)),
            "families": [f"family-{i}"],
        }
        for i in range(60)
    ]
    records[1]["sequence"] = records[0]["sequence"]
    records[3]["families"] = records[2]["families"]
    result = group_and_split(records)
    assert result[0]["biological_group_id"] == result[1]["biological_group_id"]
    assert result[2]["biological_group_id"] == result[3]["biological_group_id"]
    assert result[0]["split"] == result[1]["split"]
    groups = {}
    for row in result:
        assert groups.setdefault(row["biological_group_id"], row["split"]) == row["split"]


def test_batch_msa_parser_preserves_query_identity_and_blocks_paths():
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as archive:
        for name, text in [
            ("../../uniref.a3m", ">101\nAAA\n>hit\nCAA\n\x00>102\nCCC\n>hit\nACC\n\x00"),
            ("unrelated", "ignored"),
        ]:
            payload = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    blocks = alignment_blocks(data.getvalue())
    assert validate_a3m(blocks["101"], "AAA") == 2
    assert validate_a3m(blocks["102"], "CCC") == 2


def test_msa_restart_resumes_ticket_without_duplicate_submission(tmp_path, monkeypatch):
    from experiments import benchmark as module

    root = tmp_path / "msa"
    (root / "msas").mkdir(parents=True)
    records = [
        {"job_id": str(i), "msa": f"msas/{i}.a3m", "sequence": seq}
        for i, seq in enumerate(("AAA", "CCC"))
    ]
    atomic_json(root / "prepared.json", {"public_sequences_only": True, "records": records})
    atomic_json(root / "msa-batch-existing.ticket.json", {"id": "existing", "job_ids": ["0", "1"]})
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        data = b">101\nAAA\n>homologue\nCAA\n\x00>102\nCCC\n>homologue\nACC\n\x00"
        member = tarfile.TarInfo("uniref.a3m")
        member.size = len(data)
        archive.addfile(member, io.BytesIO(data))
    calls = []

    def request(url, data=None):
        assert data is None, "restart must not POST another server job"
        calls.append(url)
        return buffer.getvalue() if "/result/download/" in url else b'{"status":"COMPLETE"}'

    monkeypatch.setattr(module, "request", request)
    monkeypatch.setattr(
        module, "download_archive", lambda url, path: path.write_bytes(request(url))
    )
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    msa(root, 60)
    msa(root, 60)
    assert len(calls) == 2
    assert validate_a3m((root / "msas/0.a3m").read_text(), "AAA") == 2
    assert validate_a3m((root / "msas/1.a3m").read_text(), "CCC") == 2


def test_archive_stream_commits_only_complete_transfers(tmp_path, monkeypatch):
    from experiments import benchmark as module

    destination = tmp_path / "result.tar.gz"
    calls = []

    def success(_request, timeout):
        calls.append(timeout)
        return io.BytesIO(b"complete archive fixture")

    monkeypatch.setattr(module.urllib.request, "urlopen", success)
    module.download_archive("https://example.test/result", destination)
    assert destination.read_bytes() == b"complete archive fixture"
    assert calls == [180]
    assert not list(tmp_path.glob("*.part-*"))

    class InterruptedResponse(io.BytesIO):
        def read1(self, count):
            if self.tell():
                raise TimeoutError("injected transfer interruption")
            return super().read1(count)

    monkeypatch.setattr(
        module.urllib.request, "urlopen", lambda *_args, **_kwargs: InterruptedResponse(b"prefix")
    )
    incomplete = tmp_path / "incomplete.tar.gz"
    with pytest.raises(TimeoutError):
        module.download_archive("https://example.test/result", incomplete)
    assert not incomplete.exists()
    partials = list(tmp_path.glob("incomplete.tar.gz.part-*"))
    assert len(partials) == 1 and partials[0].read_bytes() == b"prefix"


def observations():
    return [
        TrainingObservation(
            f"job-{i}",
            JobFeatures("monomer", 100 + i, 100 + i),
            20 + i,
            3 + i * 0.05,
            f"group-{i}",
            "train" if i < 36 else "calibration" if i < 48 else "test",
            "test-GPU",
            "a" * 64,
        )
        for i in range(60)
    ]


def test_explicit_model_excludes_test_and_rejects_group_leakage():
    rows = observations()
    trained = train_predictor(rows, explicit_splits=True)
    changed = [
        replace(r, runtime_seconds=r.runtime_seconds * 1000) if r.split == "test" else r
        for r in rows
    ]
    again = train_predictor(changed, explicit_splits=True)
    assert trained.predictor.predict(rows[0].features) == again.predictor.predict(rows[0].features)
    assert len(trained.predictor.training_job_ids) == 36
    assert len(trained.calibration_job_ids) == 12
    rows[-1] = replace(rows[-1], biological_group_id="group-0")
    with pytest.raises(ValueError, match="crosses"):
        train_predictor(rows, explicit_splits=True)
    rows = observations()
    rows[-1] = replace(rows[-1], hardware="other-GPU")
    with pytest.raises(ValueError, match="mixed hardware"):
        train_predictor(rows, explicit_splits=True)
    rows = [
        replace(o, split="train")
        if o.split == "calibration" and int(o.job_id.split("-")[1]) >= 42
        else o
        for o in observations()
    ]
    with pytest.raises(ValueError, match="calibration groups"):
        train_predictor(rows, explicit_splits=True)


def test_campaign_matrix_resume_and_reports(tmp_path):
    benchmark = fixture_benchmark(tmp_path)
    root = tmp_path / "campaign"
    planned = plan(config_file(tmp_path, benchmark), root)
    assert len(planned["trials"]) == 6
    entries = json.loads((root / "manifests/saturated-r1.json").read_text())["jobs"]
    assert len({j["arrival_offset_seconds"] for j in entries}) == 12
    run(root, limit=1)
    first = json.loads((root / "index.json").read_text())
    completed = [v for v in first["trials"].values() if v["state"] == "COMPLETE"]
    assert len(completed) == 1
    initial_hash = completed[0]["report_sha256"]
    run(root)
    index = json.loads((root / "index.json").read_text())
    assert all(v["state"] == "COMPLETE" for v in index["trials"].values())
    assert initial_hash in {v["report_sha256"] for v in index["trials"].values()}
    rows = summarize(root, tmp_path / "report")
    assert len(rows) == 6
    assert all(r["SUCCEEDED"] == 12 and r["attempt_count"] == 12 for r in rows)
    assert (tmp_path / "report/saturated.svg").exists()
    manifest = root / next(iter(planned["manifests"]))
    manifest.write_text("{}")
    with pytest.raises(ValueError, match="manifest changed"):
        check_plan(root)


def test_default_matrix_and_transfer_integrity(tmp_path):
    benchmark = fixture_benchmark(tmp_path)
    config = config_file(tmp_path, benchmark)
    atomic_json(config, {"schema_version": "1.0", "backend": "mock", "benchmark": str(benchmark)})
    frozen = plan(config, tmp_path / "campaign")
    assert len(frozen["trials"]) == 108
    output = tmp_path / "transfer.zip"
    bundle(benchmark, output)
    verify_bundle(output)
    assert json.loads(output.with_suffix(".manifest.json").read_text())["archive_sha256"] == digest(
        output
    )
    with zipfile.ZipFile(output, "a") as archive:
        archive.writestr("unexpected.txt", "not part of the inventory")
    with pytest.raises(ValueError, match="unexpected files"):
        verify_bundle(output)


def test_profiling_stops_on_failure_and_preserves_budget(tmp_path, monkeypatch):
    from subprocess import CompletedProcess

    from experiments import vm_handoff as module

    benchmark = fixture_benchmark(tmp_path)
    calls = []
    monkeypatch.setattr(module, "busy_gpus", lambda: set())

    def launch(command, **_kwargs):
        from pathlib import Path

        calls.append(command)
        output = Path(command[command.index("--output") + 1])
        atomic_json(output, {"status": "FAILED"})
        return CompletedProcess(command, 1)

    monkeypatch.setattr(module.subprocess, "run", launch)
    output = tmp_path / "profiles"
    result = profile(benchmark, output, tmp_path, pilot=False)
    assert len(calls) == 1 and len(result["attempts"]) == 1
    spent = result["spent_seconds"]
    resumed = profile(benchmark, output, tmp_path, pilot=False)
    assert len(calls) == 1 and resumed["spent_seconds"] == spent
    exhausted = profile(benchmark, tmp_path / "exhausted", tmp_path, pilot=False, budget=0.5)
    assert not exhausted["attempts"] and len(calls) == 1
