# Vast.ai container deployment

This is a thin SSH adapter around the locally validated HelixFlow/Boltz experiment
image. The scheduler still launches native worker processes inside one container;
there is no Docker daemon, Docker-per-job, systemd, or privileged container requirement.
This does not deploy or validate the separate AWS reference architecture.

## Use the published image

Registry: [grozavlad/helixflow-vast on Docker Hub](https://hub.docker.com/r/grozavlad/helixflow-vast).

The same study image also has the user-facing alias
`grozavlad/helixflow:experimental-setup`. This does not change its contents or
SSH-oriented entrypoint. `grozavlad/helixflow:local-setup` is the separate browser
application. Keep the dated tag/digest below when reproducing the study; friendly
aliases may receive future updates.
The `2026-10-29` tag identifies the Linux AMD64 image used for the four-GPU study.
Prefer its immutable digest to protect against later tag changes:

```bash
docker pull grozavlad/helixflow-vast@sha256:b3975e8e84b8aaec09696dff987d88e8479b7a78b62e7d5bcb38d992675d06fb
docker run --rm --network none \
  grozavlad/helixflow-vast@sha256:b3975e8e84b8aaec09696dff987d88e8479b7a78b62e7d5bcb38d992675d06fb \
  helixflow-check
docker run --rm --gpus all --network none \
  grozavlad/helixflow-vast@sha256:b3975e8e84b8aaec09696dff987d88e8479b7a78b62e7d5bcb38d992675d06fb \
  helixflow-check --gpu
```

These explicit check commands do not start SSH or launch scientific jobs. Running
the image without a command starts its SSH service and requires a public key, as
described below. GPU checks require a compatible NVIDIA driver and container runtime.
Model weights, MSAs and experimental inputs are not bundled; provision them before
inference. If registry access is denied, check repository visibility or authenticate
with an account that has pull access. Anonymous access has not been verified here.

The October 30 clean-install test rebuilt a separate local image from source. That
image is not published under this tag; the archived study environment remains unchanged.

## Build locally

From the project root (`boltz_aws_paper`):

```bash
docker image inspect boltz2-multi-gpu-scheduler:prevm-20261021-ccd --format '{{.Id}}'
# Validated base ID:
# sha256:ac6147a13d7944c6ba477ad2fd53e6976b9047b2a75d46fe7ff541ad52c48b31
docker build --pull=false -t helixflow-vast:2026-10-29 multi_gpu_scheduler/deploy/vast
docker run --rm --network none helixflow-vast:2026-10-29 helixflow-check
docker run --rm --gpus all --network none helixflow-vast:2026-10-29 helixflow-check --gpu
```

The default base tag must exist locally. If it is unavailable, rebuild the scheduler
image with `multi_gpu_scheduler/Dockerfile` from the repository root and pass its tag
using `--build-arg HELIXFLOW_BASE=YOUR_BASE_TAG`. A rebuilt base is a new environment:
retain its digest/package inventory and rerun validation; do not claim the old image ID.
The adapter installs Ubuntu SSH/transfer tools but does not change Python packages.
APT packages are not snapshot-pinned: retain the built image digest and archive for
the actual study rather than assuming a future rebuild is byte-identical.

The build context allowlist includes only Dockerfile, entrypoint, check, and this
document. Model weights, MSAs, inputs, outputs, AWS keys, SSH private keys, and other
host files are not copied into this image. No jobs or downloads run at startup.

## Publish only when a registry is chosen

The tag above is local, not a registry address. Choose a repository and visibility,
then authenticate with your registry's recommended credential mechanism. For example,
after replacing `YOUR_NAMESPACE` with your own Docker Hub namespace:

```bash
docker tag helixflow-vast:2026-10-29 YOUR_NAMESPACE/helixflow-vast:2026-10-29
docker push YOUR_NAMESPACE/helixflow-vast:2026-10-29
```

These are manual instructions, not an automatic upload. Private registry pull
credentials belong in Vast's registry authentication settings, not Dockerfile layers
or a public template. Review the project and dependency licences before publishing.
Scientific assets are transferred separately, under their own terms.

## Vast template settings

| Field | Value |
| --- | --- |
| Image | Your published image address; record the registry digest after pushing |
| Launch mode | **Docker ENTRYPOINT** |
| Entrypoint arguments | Leave empty (image default is `sshd`) |
| Port | Container TCP 22; choose a host offer with direct SSH port connectivity |
| On-start script | None |
| CPU architecture | AMD64 / x86-64 |
| Disk | Start around 200 GB; check space against final output estimates |
| Rental | On-demand; enough maximum rental duration for the entire study |
| GPUs | Four identical full GPUs, preferably 24 GB+ each and Ampere or newer |

**This intentionally differs from the generic SSH-template advice:** Vast's SSH
launch mode replaces an image's entrypoint. This image supplies and tests its own
key-only SSH service; use ENTRYPOINT mode so it runs unchanged.

Before rental, add an OpenSSH public key to your Vast account. Vast documents the
`SSH_PUBLIC_KEY` environment variable; this image reads it at startup and refuses
to start without a valid public key. Never put a private key in that variable.
If it is not injected for your account, explicitly set the public key in the instance
environment. Password and keyboard-interactive authentication are disabled. Login is
`root` **inside the container only**; neither host root nor privileged mode is needed.
Only port 22 is exposed. The image supports direct SSH/SFTP/rsync, not Vast's
Jupyter portal or provider-managed SSH proxy setup. Use the mapped public IP/port.

Host SSH keys are generated at first startup, never baked into the image. They persist
for the lifetime of that container; replacement containers have new fingerprints.
Validate fingerprints from trusted instance logs/console before accepting them.
The startup environment sent to SSH sessions is allowlisted (paths, cache/lock
locations, CUDA visibility/libraries, and thread limits). Provider/API credentials
are not copied to `/etc/environment`, profiles, or SSH session environment. Container
root can still inspect container metadata; this is not a secret-isolation boundary.

## Transfer and check before experiments

Use the direct SSH command displayed by Vast with its mapped public port. For example:

```bash
ssh -p PORT root@HOST
helixflow-check --gpu
```

Confirm **four** identical visible devices and successful BF16/`nvidia-smi` checks.
Keep this same four-GPU rental allocated through the 1/2/4-GPU trials. Choose enough
reserved CPU/RAM and shared memory for four concurrent workers; GPU assignment alone
does not guarantee dedicated host CPU, disk, or network performance.

From the local project root, transfer the already prepared archive and model cache:

```bash
scp -P PORT multi_gpu_scheduler/results/handoff/helixflow-transfer-ccd-20261021.zip \
  multi_gpu_scheduler/results/handoff/helixflow-transfer-ccd-20261021.manifest.json \
  root@HOST:/workspace/
rsync -a --info=progress2 -e 'ssh -p PORT' local_install/cache/ root@HOST:/workspace/cache/
```

Inside the rental, verify before extraction. The destination `transfer` must be new:

```bash
boltz-vm verify-bundle /workspace/helixflow-transfer-ccd-20261021.zip
python -m zipfile -e /workspace/helixflow-transfer-ccd-20261021.zip /workspace/transfer
boltz-vm preflight /workspace/transfer/benchmark --cache /workspace/cache --gpus 4 \
  --inventory /workspace/helixflow-transfer-ccd-20261021.manifest.json \
  --output /workspace/results/preflight.json
```

Do **not** install the transfer bundle's source over the image's pinned installation.
Do not pass preflight `--image`: that option invokes a Docker daemon unavailable
inside this container. Record the provider's registry digest separately instead.
No cloud MSA generation or new model downloads are required with the complete cache.

Follow [VM_RUNBOOK.md](../../VM_RUNBOOK.md) from **Profile and fit on the target
hardware** onward, replacing `/workspace/benchmark` with `/workspace/transfer/benchmark`.
Run commands directly, not `docker run`/Compose inside the rental. Set explicit run
budgets, inspect the six-case pilot, and only then start full profiling/the campaign.
The image defaults to one OpenMP/OpenBLAS thread per process; record any adjustments
and hold them fixed throughout the comparison. For long runs use `tmux` so an SSH
disconnect does not terminate the experiment. No experiment auto-starts on rental.

Keep `/workspace/results` (SQLite WAL databases and GPU leases) on container-local
or block-backed storage supporting POSIX locks, **not NFS/network shared volumes**.
Vast container storage must not be assumed to survive destruction of the rental.
Stop/drain before copying complete results; for a live database use SQLite's backup
API instead of copying its `.db` alone. Download logs, receipts, structures, plans,
telemetry, and reports and verify hashes **before terminating** the instance.

## Local validation and limits

Run `python multi_gpu_scheduler/deploy/vast/test_image.py --image
helixflow-vast:2026-10-29 --output PATH.json` on a Docker host for offline package
checks, fail-closed startup, key-based SSH/SFTP, environment filtering, host-key
uniqueness, and absence of keys/assets in the image. Add `--gpu` for a bounded CUDA
check through SSH. This uses throwaway keys and loopback-only local ports, with no
credentials from your account. It does not rent hardware or publish the image.

Successful local checks do not prove Vast provisioning or multi-GPU performance.
Repeat the GPU check and preflight on the rental before the six-case pilot.

Provider references: [template settings](https://docs.vast.ai/guides/templates/template-settings),
[Docker environment and predefined variables](https://docs.vast.ai/guides/instances/docker-environment).
