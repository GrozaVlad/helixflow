# Locally built Vast adapter image — 29 October 2026

Status: **built, validated locally, and published to Docker Hub; not yet deployed on Vast**.
No paid infrastructure was created. Temporary test containers were removed; the
existing `boltz2-local` application was left running.

## Image and archive

- Local tag: `helixflow-vast:2026-10-29`
- Published tag: `docker.io/grozavlad/helixflow-vast:2026-10-29`
- Published registry digest: `sha256:b3975e8e84b8aaec09696dff987d88e8479b7a78b62e7d5bcb38d992675d06fb`
- Local Docker image ID: `sha256:b3975e8e84b8aaec09696dff987d88e8479b7a78b62e7d5bcb38d992675d06fb`
- Validated base ID: `sha256:ac6147a13d7944c6ba477ad2fd53e6976b9047b2a75d46fe7ff541ad52c48b31`
- Architecture: Linux AMD64.
- Archive: `results/handoff/helixflow-vast-2026-10-29.tar` relative to the scheduler.
- Archive size: 4,625,342,464 bytes (4.63 GB / 4.31 GiB).
- Archive SHA-256: `ba26dd5ec40a01d2f044320a7f410df71a517e6d2cea057f1a1855701a7143c2`.

The push completed successfully and Docker Hub's manifest was checked separately.
The published digest matches the validated local image ID. No image contents were
changed for publishing; only an additional repository tag was assigned. This does
not establish anonymous pull access or change the repository's visibility. If it is
private, configure registry pull credentials in Vast's template settings.

Pull the exact immutable publication on a Docker host:

```bash
docker pull grozavlad/helixflow-vast@sha256:b3975e8e84b8aaec09696dff987d88e8479b7a78b62e7d5bcb38d992675d06fb
```

To reload the saved pre-publication archive on another Docker host:

```bash
docker load --input multi_gpu_scheduler/results/handoff/helixflow-vast-2026-10-29.tar
```

## Validation evidence

Evidence is under `results/vast-image-validation-2026-10-29/` relative to the scheduler.

- `pytest-with-adapter.xml`: 52 passed (51 scheduler regression tests plus the new
  startup configuration/public-key validation test).
- `final-image-tests.json`: offline package/CLI check; complete Python package inventory
  identical to the validated base; durable queue and two native mock-worker jobs;
  key-only loopback SSH; incorrect key rejected; missing/invalid key startup refused;
  password/keyboard-interactive authentication disabled; SFTP and rsync round trips;
  allowlisted SSH environment without injected test credentials; different runtime
  host keys in separate containers; no baked keys/credentials/workspace assets;
  actual CUDA/BF16 arithmetic and GPU/compute-app telemetry through SSH.
- Ruff checks passed for the adapter. `git diff --check` passed.
- `heme-smoke.json` and `heme-smoke/`: one actual offline Boltz protein–heme prediction,
  using the existing trusted model cache and frozen `104m_1` input/MSA. Worker status
  `SUCCEEDED`, zero telemetry sample errors. Independent Gemmi parsing confirmed
  153 protein residues, one 43-heavy-atom HEM ligand including one iron atom; all
  12 artifact SHA-256 values matched the receipt.

The real smoke used reduced sampling (one recycle, 10 sampling steps, one diffusion
sample, seed 42) on the local NVIDIA RTX 5080 with 16 GB VRAM. Its approximately
19.78-second runtime and 3.89-GiB sampled whole-device peak are **readiness evidence,
not a scheduling-performance result or a memory guarantee for other targets/cards**.

Pinned environment: Python 3.11.13, PyTorch 2.7.1+cu128, Boltz 2.2.1, NumPy 1.26.4,
scikit-learn 1.6.1. The adapter adds operating-system SSH/transfer tools only.
No model weights, scientific workloads, MSAs, results, user private keys, or AWS
credentials were added to the image. Transfer scientific assets separately.

## Next steps

1. Follow [the template runbook](README.md), using image
   `grozavlad/helixflow-vast:2026-10-29`, **Docker ENTRYPOINT** mode, empty entrypoint
   arguments, container TCP port 22, and direct SSH connectivity. Add the public SSH
   key to the Vast account beforehand. Supply registry credentials if private.
2. Select and approve a suitable four-GPU rental; publication did not rent any hardware.
3. On the four-GPU rental, recheck GPU access, transfer/cache hashes, storage and
   locks. Run the six-case pilot before full profiling and the 1/2/4-GPU matrix.

Local tests do not establish provider provisioning, four-GPU resource isolation,
full-corpus fit, trained predictor quality, or experimental performance. Those
checks remain to be performed on the chosen rental.
