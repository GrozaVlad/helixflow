import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import asdict
from itertools import pairwise
from pathlib import Path

import pytest

from experiments.compare_live import compare
from experiments.live_scheduler import report
from scheduling.live import lease, run_campaign
from scheduling.live_store import connect, initialize, snapshot_input, submit
from scheduling.models import GPUDevice


def campaign(tmp_path, count=4, policy="uaf_sjf", name="campaign"):
    root = tmp_path / name
    initialize(root, {
        "backend": "mock", "policy": policy,
        "gpus": [asdict(GPUDevice(f"mock-{i}", 16)) for i in range(count)],
        "lock_dir": str(tmp_path / "locks"), "cache": str(tmp_path),
        "memory_safety": .9, "aging_seconds": 10,
        "fairness_weight": .25, "sample_interval": .1,
    })
    return root


def manifest(tmp_path, jobs):
    source = tmp_path / "protein.yaml"
    source.write_text("version: 1\nsequences:\n- protein:\n    id: A\n    sequence: AAA\n    msa: empty\n")
    entries = []
    for index, overrides in enumerate(jobs):
        entry = {
            "job_id": f"job-{index}", "owner_id": f"owner-{index % 2}",
            "input": str(source),
            "prediction": {
                "runtime_p50_seconds": 1, "runtime_p90_seconds": 2, "memory_p90_gib": 2,
            },
            "mock": {"duration_seconds": .05},
        }
        entry.update(overrides)
        entries.append(entry)
    path = tmp_path / f"manifest-{time.time_ns()}.json"
    path.write_text(json.dumps({"jobs": entries}))
    return path


def run_process(root):
    return subprocess.Popen(
        [sys.executable, "-m", "experiments.live_scheduler", "run", str(root), "--poll", ".01"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def wait_for(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.02)
    raise AssertionError("condition not met before timeout")


def assert_process_success(process):
    stdout, stderr = process.communicate(timeout=15)
    assert process.returncode == 0, stdout + stderr


@pytest.mark.parametrize("policy", ["fcfs", "token_sjf", "predicted_sjf", "fair_service", "uaf_sjf"])
def test_live_four_worker_accounting_and_nonoverlap(tmp_path, policy):
    root = campaign(tmp_path, policy=policy)
    submit(root, manifest(tmp_path, [{"mock": {"duration_seconds": .15}} for _ in range(8)]))
    run_campaign(root, poll=.01)
    payload = report(root, tmp_path / "report")
    assert payload["evidence_type"] == "mock_worker_functional_test"
    assert payload["metrics"]["counts"]["SUCCEEDED"] == 8
    assert payload["metrics"]["attempt_count"] == 8
    by_gpu = {}
    for attempt in payload["attempts"]:
        by_gpu.setdefault(attempt["gpu_id"], []).append(attempt)
    assert len(by_gpu) == 4
    for attempts in by_gpu.values():
        assert all(
            a["finished_at"] <= b["receipt"]["started_at"] for a, b in pairwise(attempts)
        )
    first_batch = [attempts[0] for attempts in by_gpu.values()]
    assert max(a["receipt"]["started_at"] for a in first_batch) < min(
        a["finished_at"] for a in first_batch
    )


def test_mock_ccd_submission_preserves_explicit_heavy_atom_counts(tmp_path):
    root = campaign(tmp_path)
    source = tmp_path / "heme.yaml"
    source.write_text("version: 1\nsequences:\n- protein: {id: A, sequence: AAA, msa: empty}\n"
                      "- ligand: {id: B, ccd: HEM}\n")
    path = manifest(tmp_path, [{"input": str(source), "ccd_atom_counts": {"HEM": 43}}])
    assert submit(root, path) == 1
    with connect(root) as db:
        spec = json.loads(db.execute("SELECT spec FROM jobs").fetchone()[0])
    assert spec["features"]["ligand_atoms"] == 43
    assert spec["features"]["estimated_tokens"] == 46


def test_retry_failure_timeout_and_unschedulable(tmp_path):
    root = campaign(tmp_path)
    path = manifest(tmp_path, [
        {"mock": {"fail_attempts": 1}, "max_attempts": 2},
        {"mock": {"missing_artifacts": True}},
        {"mock": {"duration_seconds": .4}, "timeout_seconds": .05},
        {"prediction": {"runtime_p50_seconds": 1, "runtime_p90_seconds": 2, "memory_p90_gib": 30}},
    ])
    submit(root, path)
    run_campaign(root, poll=.01)
    payload = report(root, tmp_path / "report")
    assert payload["metrics"]["counts"] == {
        "QUEUED": 0, "RUNNING": 0, "SUCCEEDED": 1, "FAILED": 2, "UNSCHEDULABLE": 1,
    }
    assert payload["metrics"]["attempt_count"] == 4
    successful = payload["jobs"][0]
    assert successful["attempt_count"] == 2
    assert successful["published_attempt"] is not None
    assert all(j["published_attempt"] is None for j in payload["jobs"][1:])


def test_restart_adopts_surviving_worker_without_duplicate(tmp_path):
    root = campaign(tmp_path, count=1)
    submit(root, manifest(tmp_path, [{"mock": {"duration_seconds": .8}, "max_attempts": 2}]))
    process = run_process(root)
    wait_for(lambda: list((root / "attempts").glob("*/worker.json")))
    process.kill()
    process.communicate(timeout=5)
    resumed = run_process(root)
    assert_process_success(resumed)
    payload = report(root, tmp_path / "report")
    assert payload["metrics"]["counts"]["SUCCEEDED"] == 1
    assert payload["metrics"]["attempt_count"] == 1


def test_killed_worker_is_recorded_and_retried(tmp_path):
    root = campaign(tmp_path, count=1)
    submit(root, manifest(tmp_path, [{"mock": {"duration_seconds": .8}, "max_attempts": 2}]))
    process = run_process(root)
    marker = wait_for(lambda: next(iter((root / "attempts").glob("*/worker.json")), None))
    os.kill(json.loads(marker.read_text())["pid"], signal.SIGKILL)
    assert_process_success(process)
    payload = report(root, tmp_path / "report")
    assert [a["status"] for a in payload["attempts"]] == ["INTERRUPTED", "SUCCEEDED"]
    assert payload["metrics"]["attempts_without_runtime_measurement"] == 1


def test_second_coordinator_rejected(tmp_path):
    root = campaign(tmp_path)
    fd = lease(root / "coordinator.lock")
    try:
        with pytest.raises(RuntimeError, match="another coordinator"):
            run_campaign(root)
    finally:
        os.close(fd)


def test_campaigns_share_gpu_lease(tmp_path):
    roots = [campaign(tmp_path, count=1, name=f"campaign-{i}") for i in range(2)]
    for root in roots:
        submit(root, manifest(tmp_path, [{"mock": {"duration_seconds": .25}}]))
    processes = [run_process(root) for root in roots]
    for process in processes:
        assert_process_success(process)
    attempts = [report(root, root / "report")["attempts"][0] for root in roots]
    attempts.sort(key=lambda a: a["receipt"]["started_at"])
    assert attempts[0]["finished_at"] <= attempts[1]["receipt"]["started_at"]


def test_duplicate_submission_and_input_tamper(tmp_path):
    root = campaign(tmp_path)
    path = manifest(tmp_path, [{}])
    submit(root, path)
    with pytest.raises(ValueError, match="already exists"):
        submit(root, path)
    with connect(root) as db:
        spec = json.loads(db.execute("SELECT spec FROM jobs").fetchone()[0])
    Path(spec["input"]).write_text("modified")
    run_campaign(root, poll=.01)
    payload = report(root, tmp_path / "report")
    assert payload["metrics"]["counts"]["FAILED"] == 1
    assert "modified" in payload["jobs"][0]["reason"]


def test_msa_validation_and_staging(tmp_path):
    source = tmp_path / "input.yaml"
    source.write_text("version: 1\nsequences:\n- protein:\n    id: A\n    sequence: AAA\n    msa: x.a3m\n")
    (tmp_path / "x.a3m").write_text(">query\nBBB\n")
    with pytest.raises(ValueError, match="does not match"):
        snapshot_input(source, tmp_path / "bad")
    (tmp_path / "x.a3m").write_text(">query\nAAA\n>other\nA-A\n")
    staged, hashes = snapshot_input(source, tmp_path / "good")
    assert staged.is_file()
    assert len(hashes) == 2
    assert str(tmp_path / "good" / "msa-0.a3m") in staged.read_text()


def test_deferred_arrival_runs_after_ready_time(tmp_path):
    root = campaign(tmp_path, count=2)
    submit(root, manifest(tmp_path, [
        {"mock": {"duration_seconds": .5}},
        {"arrival_offset_seconds": .1},
    ]))
    run_campaign(root, poll=.01)
    payload = report(root, tmp_path / "report")
    jobs = {j["job_id"]: j for j in payload["jobs"]}
    attempts = {a["job_id"]: a for a in payload["attempts"]}
    assert attempts["job-1"]["claimed_at"] >= jobs["job-1"]["ready_at"]
    assert attempts["job-1"]["claimed_at"] < attempts["job-0"]["finished_at"]


def test_mock_comparison_needs_explicit_label_and_rejects_changed_workload(tmp_path):
    root = campaign(tmp_path)
    submit(root, manifest(tmp_path, [{}]))
    run_campaign(root, poll=.01)
    payload = report(root, tmp_path / "report")
    path = tmp_path / "report" / "report.json"
    with pytest.raises(ValueError, match="mock"):
        compare([path])
    assert compare([path], allow_mock=True)[0]["SUCCEEDED"] == 1
    payload["jobs"][0]["spec"]["options"]["sampling_steps"] += 1
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="not matched"):
        compare([path, changed], allow_mock=True)


def test_mock_profiles_cannot_be_used_for_training(tmp_path, monkeypatch):
    from experiments.profiles_to_csv import main
    root = campaign(tmp_path)
    submit(root, manifest(tmp_path, [{}]))
    run_campaign(root, poll=.01)
    report(root, tmp_path / "report")
    profile = next((tmp_path / "report" / "profiles").glob("*.json"))
    monkeypatch.setattr(sys, "argv", ["profiles-to-csv", str(profile),
                                     "--output", str(tmp_path / "bad.csv")])
    with pytest.raises(ValueError, match="mock"):
        main()


def test_partial_batch_submission_is_not_accepted(tmp_path):
    root = campaign(tmp_path)
    invalid = manifest(tmp_path, [{}, {"max_attempts": 0}])
    with pytest.raises(ValueError, match="max_attempts"):
        submit(root, invalid)
    with connect(root) as db:
        assert db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0


def test_success_receipt_recovery_checks_artifact_integrity(tmp_path):
    root = campaign(tmp_path)
    submit(root, manifest(tmp_path, [{}]))
    run_campaign(root, poll=.01)
    with connect(root) as db:
        attempt = dict(db.execute("SELECT * FROM attempts").fetchone())
        # Simulate a receipt written before its state transaction was committed.
        db.execute("UPDATE attempts SET status='RUNNING'")
        db.execute("UPDATE jobs SET status='RUNNING',published_attempt=NULL")
    (root / "attempts" / attempt["attempt_id"] / "output" / "MOCK_ONLY.txt").write_text("tamper")
    run_campaign(root, poll=.01)
    payload = report(root, tmp_path / "report")
    assert payload["metrics"]["counts"]["FAILED"] == 1
    assert payload["jobs"][0]["published_attempt"] is None


def test_real_worker_child_retains_lease_after_supervisor_kill(tmp_path, monkeypatch):
    """Exercise real subprocess/descriptor handling, using a fake Boltz executable."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    smi = bindir / "nvidia-smi"
    smi.write_text(
        f"#!{sys.executable}\nimport sys\n"
        "if any('uuid,memory.total' in a for a in sys.argv): print('mock-0, 16384')\n"
        "elif any('memory.used,utilization.gpu' in a for a in sys.argv): print('100, 0')\n"
    )
    smi.chmod(0o755)
    executable = bindir / "boltz"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import sys,time\nfrom pathlib import Path\n"
        "out=Path(sys.argv[sys.argv.index('--out_dir')+1])\n"
        "(out/'child_started').write_text(str(time.time()))\n"
        "time.sleep(0.8)\n"
        "p=out/'boltz_results_input'/'predictions'/'input'\np.mkdir(parents=True)\n"
        "(p/'input_model_0.cif').write_text('data_fake_test_only\\n')\n"
        "(p/'confidence_input_model_0.json').write_text('{\"confidence_score\":0.1}')\n"
        "(out/'child_finished').write_text(str(time.time()))\n"
    )
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    root = campaign(tmp_path, count=1)
    with connect(root) as db:
        settings = json.loads(db.execute("SELECT value FROM metadata").fetchone()[0])
        settings["backend"] = "boltz"
        db.execute("UPDATE metadata SET value=?", (json.dumps(settings),))
    path = manifest(tmp_path, [{"max_attempts": 2}])
    data = json.loads(path.read_text())
    data["jobs"][0].pop("mock")
    path.write_text(json.dumps(data))
    submit(root, path)
    process = run_process(root)
    first = wait_for(lambda: next(iter((root / "attempts").glob("*/output/child_started")), None))
    folder = first.parent.parent
    worker_pid = json.loads((folder / "worker.json").read_text())["pid"]
    os.kill(worker_pid, signal.SIGKILL)
    time.sleep(.1)
    assert lease(tmp_path / "locks" / "mock-0.lock") is None
    assert_process_success(process)
    payload = report(root, tmp_path / "report")
    assert [a["status"] for a in payload["attempts"]] == ["INTERRUPTED", "SUCCEEDED"]
    command = payload["attempts"][1]["receipt"]["command"]
    assert command[command.index("--seed") + 1] == "42"
    first_finished = float((folder / "output" / "child_finished").read_text())
    assert payload["attempts"][1]["receipt"]["started_at"] >= first_finished


def test_graceful_stop_drains_active_worker_and_preserves_queue(tmp_path):
    root = campaign(tmp_path, count=1)
    submit(root, manifest(tmp_path, [
        {"mock": {"duration_seconds": .4}}, {"mock": {"duration_seconds": .1}},
    ]))
    process = run_process(root)
    wait_for(lambda: list((root / "attempts").glob("*/worker.json")))
    process.terminate()
    assert_process_success(process)
    with connect(root) as db:
        states = [r[0] for r in db.execute("SELECT status FROM jobs ORDER BY job_id")]
    assert states == ["SUCCEEDED", "QUEUED"]
    run_campaign(root, poll=.01)
    assert report(root, tmp_path / "report")["metrics"]["counts"]["SUCCEEDED"] == 2


def test_trusted_model_overrides_manual_prediction(tmp_path, monkeypatch):
    from scheduling.models import RuntimePrediction
    from scheduling.predictor import PredictorBundle

    class Model:
        def predict(self, features):
            assert features.total_residues == 3
            return RuntimePrediction(3, 5, 7)

    monkeypatch.setattr(PredictorBundle, "load", lambda _path: Model())
    root = campaign(tmp_path)
    model = tmp_path / "trusted.pkl"
    model.write_bytes(b"mocked model loader")
    submit(root, manifest(tmp_path, [{}]), model)
    with connect(root) as db:
        spec = json.loads(db.execute("SELECT spec FROM jobs").fetchone()[0])
    assert spec["prediction"]["runtime_p90_seconds"] == 5
    assert spec["prediction_source"].startswith("trusted-model-sha256:")
