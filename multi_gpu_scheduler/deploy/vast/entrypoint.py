"""Key-only SSH for Vast ENTRYPOINT mode, without exposing account secrets to sessions."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Deliberately NOT the entire environment: Vast injects an instance API key, and
# credentials supplied for provisioning must not be copied into login dotfiles.
SESSION_DEFAULTS = {
    "PATH": "/opt/conda/bin:/usr/local/nvidia/bin:/usr/local/cuda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "BOLTZ_CACHE": "/workspace/cache",
    "HELIXFLOW_SOURCE": "/opt/multi_gpu_scheduler",
    "HELIXFLOW_LOCK_DIR": "/workspace/results/gpu-locks",
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
}
SESSION_OPTIONAL = (
    "CUDA_VISIBLE_DEVICES",
    "NVIDIA_VISIBLE_DEVICES",
    "NVIDIA_DRIVER_CAPABILITIES",
    "LD_LIBRARY_PATH",
)


def public_keys(value: str) -> str:
    """Accept only plain, valid public keys, never authorized_keys options."""
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines:
        raise ValueError("SSH_PUBLIC_KEY is required; add your public key to the Vast account")
    for line in lines:
        fields = line.split()
        if len(fields) < 2 or not fields[0].startswith(("ssh-", "ecdsa-", "sk-")):
            raise ValueError("SSH_PUBLIC_KEY must contain plain OpenSSH public keys")
        result = subprocess.run(
            ["ssh-keygen", "-l", "-f", "-"],
            input=line + "\n",
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            raise ValueError("SSH_PUBLIC_KEY contains an invalid OpenSSH public key")
    return "\n".join(lines) + "\n"


def session_environment(environ: dict[str, str]) -> dict[str, str]:
    result = {name: environ.get(name, value) for name, value in SESSION_DEFAULTS.items()}
    result.update({name: environ[name] for name in SESSION_OPTIONAL if name in environ})
    # PATH is fixed so a provisioning environment cannot select a different Python.
    result["PATH"] = SESSION_DEFAULTS["PATH"]
    for name, value in result.items():
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError(f"invalid control character in {name}")
    return result


def configuration(environ: dict[str, str]) -> str:
    lines = [
        "Port 22",
        "ListenAddress 0.0.0.0",
        "HostKey /etc/ssh/ssh_host_ed25519_key",
        "PidFile /run/helixflow/sshd.pid",
        "AuthorizedKeysFile /root/.ssh/authorized_keys",
        "AllowUsers root",
        "PermitRootLogin prohibit-password",
        "PubkeyAuthentication yes",
        "AuthenticationMethods publickey",
        "PasswordAuthentication no",
        "KbdInteractiveAuthentication no",
        "PermitEmptyPasswords no",
        "UsePAM yes",
        "X11Forwarding no",
        "AllowAgentForwarding no",
        "AllowTcpForwarding local",
        "PermitTunnel no",
        "PermitUserEnvironment no",
        "PrintMotd no",
        "LogLevel VERBOSE",
        "Subsystem sftp internal-sftp",
    ]
    settings = []
    for name, value in session_environment(environ).items():
        quoted = value.replace("\\", "\\\\").replace('"', '\\"')
        settings.append(f'"{name}={quoted}"')
    # sshd uses the first SetEnv directive only; all pairs must be on one line.
    lines.append("SetEnv " + " ".join(settings))
    return "\n".join(lines) + "\n"


def main() -> None:
    args = sys.argv[1:] or ["sshd"]
    if args != ["sshd"]:
        os.execvp(args[0], args)
    if os.geteuid() != 0:
        raise ValueError("SSH startup needs container root (not host privileged mode)")
    keys = public_keys(os.environ.get("SSH_PUBLIC_KEY", ""))
    config = configuration(dict(os.environ))
    os.umask(0o077)
    for path in ("/run/sshd", "/run/helixflow", "/root/.ssh"):
        Path(path).mkdir(parents=True, exist_ok=True)
    Path("/root/.ssh").chmod(0o700)
    auth = Path("/root/.ssh/authorized_keys")
    auth.write_text(keys)
    auth.chmod(0o600)
    host_key = Path("/etc/ssh/ssh_host_ed25519_key")
    if not host_key.exists():
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(host_key)],
            check=True,
        )
    for path in ("/workspace/cache", "/workspace/results", "/workspace/results/gpu-locks"):
        Path(path).mkdir(parents=True, exist_ok=True)
    target = Path("/run/helixflow/sshd_config")
    target.write_text(config)
    subprocess.run(["/usr/sbin/sshd", "-t", "-f", str(target)], check=True)
    subprocess.run(["ssh-keygen", "-l", "-f", str(host_key) + ".pub"], check=True)
    # Remove transient provider/provisioning credentials from sshd's inherited
    # environment too. Only explicitly allowlisted values reach SSH sessions.
    env = {"LANG": "C.UTF-8", **session_environment(dict(os.environ))}
    print("HelixFlow: key-only SSH ready on container port 22; no jobs auto-started", flush=True)
    os.execve("/usr/sbin/sshd", ["/usr/sbin/sshd", "-D", "-e", "-f", str(target)], env)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, subprocess.CalledProcessError) as exc:
        print(f"HelixFlow startup refused: {exc}", file=sys.stderr)
        sys.exit(1)
