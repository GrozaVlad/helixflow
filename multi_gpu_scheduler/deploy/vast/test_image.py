"""Local Docker/SSH integration tests; no account credentials or cloud resources used."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shlex
import subprocess
import tempfile
import time
import uuid
from pathlib import Path


def run(command, *, check=True, input=None):
    return subprocess.run(command, check=check, input=input, capture_output=True, text=True)


def test_entrypoint_helpers():
    spec = importlib.util.spec_from_file_location(
        "vast_entrypoint", Path(__file__).with_name("entrypoint.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for key in ("", "not a public key", 'command="bad" ssh-ed25519 fake', "ssh-ed25519 fake"):
        try:
            module.public_keys(key)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid public key accepted")
    env = module.session_environment(
        {"CONTAINER_API_KEY": "test-secret", "PATH": "/wrong", "CUDA_VISIBLE_DEVICES": "GPU-test"}
    )
    assert "CONTAINER_API_KEY" not in env
    assert env["PATH"].startswith("/opt/conda/bin:")
    assert env["CUDA_VISIBLE_DEVICES"] == "GPU-test"
    config = module.configuration({})
    assert '"BOLTZ_CACHE=/workspace/cache"' in config
    assert config.count("SetEnv ") == 1
    for value in ("x\nPasswordAuthentication yes", "x\r", "x\x00", "x\x7f"):
        try:
            module.session_environment({"BOLTZ_CACHE": value})
        except ValueError:
            pass
        else:
            raise AssertionError("control character accepted in SSH config")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="helixflow-vast:2026-10-29")
    parser.add_argument("--base", default="boltz2-multi-gpu-scheduler:prevm-20261021-ccd")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--gpu", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("use a new output path; preserve previous evidence")
    test_entrypoint_helpers()
    evidence = {"schema_version": "1.0", "checked_at": time.time(), "checks": []}
    image = json.loads(run(["docker", "image", "inspect", args.image]).stdout)[0]
    evidence["image"] = {k: image[k] for k in ("Id", "RepoTags", "RepoDigests", "Architecture")}

    def docker(*command, **kwargs):
        return run(["docker", *command], **kwargs)

    check = docker("run", "--rm", "--network", "none", args.image, "helixflow-check")
    evidence["offline_check"] = json.loads(check.stdout)
    evidence["checks"].append("offline_pinned_packages_and_cli")
    package_probe = (
        "import importlib.metadata as m,json; "
        "print(json.dumps({d.metadata['Name']:d.version for d in m.distributions()},sort_keys=True))"
    )
    base_packages = json.loads(
        docker("run", "--rm", "--network", "none", args.base, "python", "-c", package_probe).stdout
    )
    new_packages = json.loads(
        docker("run", "--rm", "--network", "none", args.image, "python", "-c", package_probe).stdout
    )
    assert base_packages == new_packages, "SSH adapter changed Python package inventory"
    evidence["python_packages"] = new_packages
    evidence["checks"].append("all_python_packages_unchanged_from_validated_base")
    worker_probe = """
import json, subprocess, tempfile
from pathlib import Path
with tempfile.TemporaryDirectory(prefix='helixflow-queue-test-') as scratch:
    root = Path(scratch) / 'queue'
    commands = [
        ['boltz-live', 'init', str(root), '--mock', '--mock-gpus', '4'],
        ['boltz-live', 'submit', str(root), '/opt/multi_gpu_scheduler/examples/live_smoke.json'],
        ['boltz-live', 'run', str(root)],
        ['boltz-live', 'export', str(root), '--output', str(Path(scratch) / 'report')],
    ]
    for command in commands:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
    report = json.loads((Path(scratch) / 'report' / 'report.json').read_text())
    assert report['metrics']['counts']['SUCCEEDED'] == 2
    assert report['metrics']['all_terminal']
    assert report['evidence_type'] == 'mock_worker_functional_test'
    print(json.dumps({'evidence_type':report['evidence_type'], 'metrics':report['metrics']}))
"""
    evidence["mock_queue_check"] = json.loads(
        docker("run", "--rm", "--network", "none", args.image, "python", "-c", worker_probe).stdout
    )
    evidence["checks"].append("durable_queue_and_native_mock_workers")
    audit_code = (
        "from pathlib import Path; import json; "
        "print(json.dumps({'host_keys':list(map(str,Path('/etc/ssh').glob('ssh_host_*'))),"
        "'workspace_files':[str(p) for p in Path('/workspace').rglob('*') if p.is_file()],"
        "'credentials':[str(p) for d in ('/root/.ssh','/root/.aws') "
        "for p in Path(d).rglob('*') if p.is_file()]}))"
    )
    audit = json.loads(
        docker("run", "--rm", "--network", "none", args.image, "python", "-c", audit_code).stdout
    )
    assert not any(audit.values()), "image contains host keys, credentials, or workspace assets"
    evidence["image_audit"] = audit
    evidence["checks"].append("no_baked_host_keys_credentials_or_workspace_assets")
    for value in (None, "not-a-key"):
        command = ["run", "--rm", "--network", "none"]
        if value:
            command += ["-e", f"SSH_PUBLIC_KEY={value}"]
        result = docker(*command, args.image, check=False)
        assert result.returncode != 0 and "SSH_PUBLIC_KEY" in result.stderr
    evidence["checks"].append("missing_and_invalid_keys_fail_closed")

    containers = []
    with tempfile.TemporaryDirectory(prefix="helixflow-vast-test-") as scratch:
        directory = Path(scratch)
        key = directory / "id_ed25519"
        wrong_key = directory / "wrong_ed25519"
        for target in (key, wrong_key):
            run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(target)])
        public = key.with_suffix(".pub").read_text().strip()
        known = directory / "known_hosts"
        try:
            fingerprints = []
            for number in range(2):
                name = f"helixflow-vast-test-{uuid.uuid4().hex[:12]}"
                gpu_options = ["--gpus", "all"] if args.gpu and number == 0 else []
                docker(
                    "run",
                    "-d",
                    "--name",
                    name,
                    *gpu_options,
                    "-p",
                    "127.0.0.1::22",
                    "-e",
                    f"SSH_PUBLIC_KEY={public}",
                    "-e",
                    "CONTAINER_API_KEY=helixflow-test-secret",
                    "-e",
                    "AWS_SECRET_ACCESS_KEY=helixflow-test-secret",
                    args.image,
                )
                containers.append(name)
                port = docker("port", name, "22/tcp").stdout.strip().rsplit(":", 1)[1]
                options = [
                    "-i",
                    str(key),
                    "-o",
                    "IdentitiesOnly=yes",
                    "-o",
                    "IdentityAgent=none",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "ConnectTimeout=2",
                    "-o",
                    "StrictHostKeyChecking=accept-new",
                    "-o",
                    f"UserKnownHostsFile={known}",
                ]

                def ssh(command, *, check=True, options=options, port=port):
                    return run(
                        ["ssh", *options, "-p", port, "root@127.0.0.1", command], check=check
                    )

                for _ in range(60):
                    ready = ssh("true", check=False)
                    if ready.returncode == 0:
                        break
                    state = json.loads(docker("inspect", name).stdout)[0]["State"]
                    if state["Status"] != "running":
                        raise RuntimeError(
                            "test SSH container exited: " + docker("logs", name).stderr
                        )
                    time.sleep(0.25)
                else:
                    raise RuntimeError("SSH did not become ready: " + ready.stderr)
                fingerprint = docker(
                    "exec", name, "ssh-keygen", "-l", "-f", "/etc/ssh/ssh_host_ed25519_key.pub"
                ).stdout.strip()
                fingerprints.append(fingerprint.split()[1])
                if number == 1:
                    break
                env_probe = (
                    "import json,os,sys; print(json.dumps({'python':sys.executable,"
                    "'cache':os.environ.get('BOLTZ_CACHE'),'locks':os.environ.get('HELIXFLOW_LOCK_DIR'),"
                    "'credentials_present':any(k in os.environ for k in "
                    "['CONTAINER_API_KEY','AWS_SECRET_ACCESS_KEY','SSH_PUBLIC_KEY'])}))"
                )
                env = json.loads(ssh(shlex.join(["python", "-c", env_probe])).stdout)
                assert env["python"] == "/opt/conda/bin/python"
                assert env["cache"] == "/workspace/cache", repr(env)
                assert env["locks"] == "/workspace/results/gpu-locks", repr(env)
                assert not env["credentials_present"]
                evidence["ssh_session"] = env
                evidence["ssh_package_check"] = json.loads(ssh("helixflow-check").stdout)
                ssh("boltz-live --help >/dev/null && boltz-campaign --help >/dev/null")
                config = docker(
                    "exec", name, "/usr/sbin/sshd", "-T", "-f", "/run/helixflow/sshd_config"
                ).stdout
                for expected in (
                    "passwordauthentication no",
                    "kbdinteractiveauthentication no",
                    "authenticationmethods publickey",
                    "permituserenvironment no",
                ):
                    assert expected in config
                bad_options = list(options)
                bad_options[1] = str(wrong_key)
                denied = run(
                    ["ssh", *bad_options, "-p", port, "root@127.0.0.1", "true"], check=False
                )
                assert denied.returncode == 255 and "Permission denied" in denied.stderr
                source = directory / "sftp-input.txt"
                destination = directory / "sftp-output.txt"
                source.write_text("HelixFlow transfer smoke test\n")
                run(
                    ["sftp", *options, "-P", port, "-b", "-", "root@127.0.0.1"],
                    input=(
                        f"put {source} /workspace/sftp-test.txt\n"
                        f"get /workspace/sftp-test.txt {destination}\n"
                    ),
                )
                assert source.read_bytes() == destination.read_bytes()
                run(
                    [
                        "rsync",
                        "-a",
                        "-e",
                        shlex.join(["ssh", *options, "-p", port]),
                        str(source),
                        "root@127.0.0.1:/workspace/rsync-test.txt",
                    ]
                )
                assert (
                    ssh("sha256sum /workspace/sftp-test.txt").stdout.split()[0]
                    == ssh("sha256sum /workspace/rsync-test.txt").stdout.split()[0]
                )
                if args.gpu:
                    evidence["ssh_gpu_check"] = json.loads(ssh("helixflow-check --gpu").stdout)
                    evidence["checks"].append("cuda_bf16_and_nvidia_smi_through_ssh")
                evidence["checks"] += [
                    "ssh_key_login",
                    "wrong_key_rejected",
                    "password_authentication_disabled",
                    "ssh_pinned_python_and_cli",
                    "ssh_environment_allowlist",
                    "sftp_and_rsync_roundtrip",
                ]
            assert len(set(fingerprints)) == 2, "host private key was reused across containers"
            evidence["host_key_fingerprints"] = fingerprints
            evidence["checks"].append("unique_runtime_host_keys")
        finally:
            for name in containers:
                docker("rm", "-f", name, check=False)
    evidence["status"] = "PASSED"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": "PASSED",
                "image_id": image["Id"],
                "checks": evidence["checks"],
                "report": str(args.output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
