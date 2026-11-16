# HelixFlow

HelixFlow provides tools for executing Boltz-2 biomolecular prediction workflows:
a local browser workbench, a durable single-host multi-GPU scheduler, and an
experimental AWS reference backend. It manages jobs and scientific artifacts;
it does not replace Boltz or validate pharmacological efficacy.

## Components

| Directory | Contents |
| --- | --- |
| [local_install](local_install/README.md) | Single-GPU browser app, logs, downloads and Mol* structure viewer |
| [multi_gpu_scheduler](multi_gpu_scheduler/README.md) | CLI dispatcher, profiling, resource predictors, scheduling policies, tests and experiment tools |
| [aws_distributed](aws_distributed/README.md) | Experimental API, SQS/Step Functions/Batch workers and Terraform definitions |
| [artifacts](artifacts/README.md) | Paper evidence, workload definitions, analysis scripts and figures; no manuscript |

The browser and multi-GPU CLI are separate interfaces. The runner uses independent
Boltz processes on one host, not multi-node or distributed-model parallelism.
The AWS backend has not been validated by a cloud deployment; FSx provisioning,
MSA integration, state/retry correctness and authenticated HTTPS remain incomplete.

## Start the local workbench

On a Linux host with a compatible NVIDIA driver, Docker and NVIDIA Container Toolkit:

```bash
cd local_install
docker compose -f compose.prebuilt.yaml pull
docker compose -f compose.prebuilt.yaml up -d
```

Open http://127.0.0.1:8000. First use may download model assets. Automatic MSA
generation can send sequences to the configured external service; use compatible
precomputed alignments for sensitive inputs. See the component README for details.
The dedicated browser image is `grozavlad/helixflow:local-setup`
(Linux AMD64). This installation does not build the application. Stop with
`docker compose -f compose.prebuilt.yaml down`; cached models and results remain
on the host. Source builds remain available through `local_install/run.sh`.

For multi-GPU execution, follow [LIVE_EXECUTION.md](multi_gpu_scheduler/LIVE_EXECUTION.md).
The study/scheduler image is `grozavlad/helixflow:experimental-setup`, Linux AMD64.
Its original dated tag `grozavlad/helixflow-vast:2026-10-29` remains unchanged.
For the exact experimental artifact, pull by digest:

```bash
docker pull grozavlad/helixflow-vast@sha256:b3975e8e84b8aaec09696dff987d88e8479b7a78b62e7d5bcb38d992675d06fb
```

This image contains the scheduler and Boltz runtime, not the browser, model weights,
MSAs or results. Its default entrypoint is a key-only SSH adapter. Follow the
[image runbook](multi_gpu_scheduler/deploy/vast/README.md) for configuration and
explicit command execution. Registry visibility must be verified before release.

Both friendly aliases are published under `grozavlad/helixflow`. They may receive
updates; dated tags and recorded immutable digests identify the tested versions.
The current browser dated tag is `local-2026-11-16`; see
[local image release notes](local_install/release/README.md) for its digest.

## Validation and reproduction

The study completed 108 trials / 1,296 jobs on one four-RTX-4090 host, with
one-, two- and four-GPU configurations. Separate process-recovery and clean-container
checks are documented in [VALIDATION.md](multi_gpu_scheduler/VALIDATION.md).
Repeated runs do not represent independent biological samples or cloud validation.

```bash
python3 artifacts/verify_artifacts.py
python3 -m venv .venv
.venv/bin/pip install -r artifacts/requirements.txt
.venv/bin/python artifacts/generate_results.py
```

See [artifacts/README.md](artifacts/README.md) for the distinction between reproducing
plots and rerunning inference. Manuscript sources/PDFs remain outside this repository.

## Authors, support and release status

Vlad Mircea Groza and Mihai Udrescu, Department of Computer and Information Technology,
Politehnica University Timișoara. Support: **mihai.udrescu@cs.upt.ro**.

This repository is prepared for a public software release; no paper DOI or archival
release DOI has been assigned here. Freeze a release and publish the supporting
archive before claiming complete public reproducibility. See [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md).
Project source declares Apache-2.0; upstream software, model and scientific-data
licenses remain separate. Licensing/third-party attribution review is still pending.
