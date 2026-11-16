# Local workbench image: local-2026-11-16

The browser application image is separate from the unchanged Vast study image.
It targets Linux AMD64 and starts FastAPI/uvicorn directly on port 8000; no SSH
configuration or source build is required for users.

Publication completed on 16 November 2026. A pull by digest with an empty Docker
client configuration succeeded, verifying public access without account credentials.

```sh
docker pull grozavlad/helixflow:local-2026-11-16
```

The user-facing alias is `grozavlad/helixflow:local-setup`; the prebuilt Compose
file uses it by default. It currently resolves to the same digest below. The
companion `grozavlad/helixflow:experimental-setup` alias resolves to the unchanged
study image digest
`sha256:b3975e8e84b8aaec09696dff987d88e8479b7a78b62e7d5bcb38d992675d06fb`.
Neither alias replaces or removes the dated tags. Use a digest for reproducibility
because friendly aliases may be updated in future releases.

For the exact tested artifact, use the immutable registry digest:

```sh
docker pull grozavlad/helixflow@sha256:df1e25abac08fd1490f419815f3ff11528fe7b9ae14c43b3b57c9033c5ee3e35
```

With `compose.prebuilt.yaml`, pin the image explicitly:

```sh
HELIXFLOW_IMAGE=grozavlad/helixflow@sha256:df1e25abac08fd1490f419815f3ff11528fe7b9ae14c43b3b57c9033c5ee3e35 docker compose -f compose.prebuilt.yaml up -d
```

## Contents and requirements

The image includes Boltz 2.2.1, the CUDA/PyTorch runtime, FastAPI, the browser UI,
locally served Mol* assets, and example input files. The image's logical size
reported by Docker is 4,604,639,473 bytes; compressed download and local shared-layer
storage differ. It does not contain model checkpoints, the host model cache,
historical jobs, SSH configuration, or AWS credentials. A compatible NVIDIA
driver and NVIDIA Container Toolkit are required for GPU inference.

The first normal prediction downloads model assets unless a populated cache is
mounted. Automatic MSA generation uses an external service and transmits protein
sequences; use a compatible frozen alignment for sensitive/offline work. The
application is intended for trusted localhost use and has no production user
authentication. Publication of an image is not a security audit.

## Validation performed before publication

- Built from this repository's `local_install` directory.
- `pip check` and Python compilation passed.
- Checked absence of `/workspace/cache`, `/workspace/data`, `/root/.aws`, and
  `/root/.ssh` in the unstarted image.
- Started a separate GPU-enabled container with empty input/output directories,
  a read-only existing model cache, and a frozen MSA.
- Submitted a real estradiol–ESR1 prediction via `POST /api/jobs`; verified GPU
  health, both successful prediction stages, downloadable CIF and score files,
  absence of MSA mismatch, and delivery of the fixed viewer and Mol* JavaScript.
- All eight API smoke checks passed. The approximately 48.07-second observed
  interval includes polling delay and is not a study benchmark.

`validation-local-2026-11-16.json` preserves the exact API job, log, checks, and
download hashes. `smoke_test.py` reproduces this acceptance procedure against a
fresh isolated service. This test used cached model assets; it did not validate
fresh remote model downloads, remote MSA availability, or browser WebGL rendering.

The test container was removed after validation; its downloaded/host-side test
outputs were retained. The user's existing local workbench was not replaced.

## Build identity

Base: `pytorch/pytorch:2.7.1-cuda12.8-cudnn9-runtime`, resolved during the build to
`sha256:c16f4c749e2d9e96878875cdf6cc45cddda1d1a36fddd371dd6f2360f1b6e2a2`.
The OCI labels identify this repository and the `local-2026-11-16` release. No Git
commit is claimed because the prepared source tree had not been committed.

| Source | SHA-256 |
| --- | --- |
| Dockerfile | `69560a66ece14481356efc9ed84226c0e2d6c0c5e1127a21af5a3a46d3a90d06` |
| requirements.txt | `80d4acc0daa67ef7f2b5c727f0e49226590bb84f4099e0a099c3b61bba0ff300` |
| app/main.py | `abd4ec0e6214dd142def3e4a93422bd944ccefb79e54911b86ebaa39c1392968` |
| app/static/viewer.js | `e5b1e7e00ee331ff9c5dc87fb31530e0652008d30b8d59695f4782788440a688` |

Future source builds may resolve different transitive dependencies. Use the
published digest for the exact released image; a tag alone is not immutable.
