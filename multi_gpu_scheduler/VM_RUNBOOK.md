# VM experiment runbook

Prepare and transfer the image, public workload, frozen MSAs, and cached Boltz assets
before running the paid experiment matrix. The VM needs Linux, a compatible NVIDIA
driver, Docker with GPU support, four GPUs, and sufficient local output storage.

## Prepare locally

For the published experiment inputs, prefer `public-v1-heme-ccd-public.tar.gz`
and its included README/data notice instead of requesting new alignments.
It omits mixed-provider API cache records but preserves the original frozen
fingerprint and every execution input. Run its standalone verifier first.
The updated scheduler recognizes `public-release.json` and verifies every
included file; the historical container image requires the source overlay
documented in that README. Full workload validation remains strict when no
public-release manifest is present. Do not use the public projection for source
preparation or ligand revisions, and keep generated files outside its directory.

From `multi_gpu_scheduler`, the development CLIs can be installed with
`python -m pip install -e '.[dev,experiment]'`. The container includes experiment tools.
Prepared local artifacts are listed in [PREVM_VALIDATION.md](PREVM_VALIDATION.md).
The corrected image uses tag `boltz2-multi-gpu-scheduler:prevm-20261021-ccd`; after loading,
tag it as `helixflow:experiment` to follow the examples below.

```bash
boltz-benchmark fetch workloads/public-v1
boltz-benchmark prepare workloads/public-v1
boltz-benchmark msa workloads/public-v1 --limit 60
boltz-benchmark freeze workloads/public-v1
boltz-benchmark validate workloads/public-v1
```

Use the existing catalog and prepared files when resuming. Fetch and prepare deliberately
refuse to overwrite them. MSA preparation resumes the same server tickets. Freeze is
performed once, after every MSA is valid. Subsequent validation verifies the inventory.
Result downloads stream to partial files and print byte progress. A failed transfer
retains its partial file for diagnosis; the public endpoint does not support HTTP
byte ranges, so retrying transfers the same completed result again. It does not
submit another alignment computation. The download read timeout is 180 seconds.

Build the environment from the repository root, inspect its image ID, and retain that
identifier with the experiment evidence:

```bash
docker build -f multi_gpu_scheduler/Dockerfile -t helixflow:experiment .
docker image inspect helixflow:experiment --format '{{.Id}}'
docker save -o helixflow-image.tar helixflow:experiment
```

The active corpus is `workloads/public-v1-heme-ccd`. It retains all 60 targets,
partitions, settings and MSA bytes from `public-v1`, but uses cached `ccd: HEM` for
the two heme ligands whose SMILES conformer generation failed. Preserve the original
frozen corpus and failed attempt. Reproduce the revision inside the Boltz/RDKit
environment, with both workload directories and the trusted molecular cache mounted:

```bash
boltz-benchmark revise-ligands /workspace/workloads/public-v1 \
  --output /workspace/workloads/public-v1-heme-ccd --ccd HEM --cache /workspace/cache
```

The command refuses an existing destination, verifies cached heavy-atom counts against
the source catalog, records the source fingerprint and changed inputs, and freezes a new
inventory. It performs no network requests. For existing revisions, use `validate` instead.
Before inference, check every input with the pinned Boltz parser on CPU; valid SMILES
syntax alone does not establish that conformer generation will succeed.

Create a research transfer bundle and verify it:

```bash
boltz-vm bundle workloads/public-v1-heme-ccd --cache ../local_install/cache \
  --output results/handoff/helixflow-transfer.zip
boltz-vm verify-bundle results/handoff/helixflow-transfer.zip
```

The bundle contains source, configuration, scientific inputs, MSAs, source records,
and an embedded SHA-256 inventory. The sidecar records the ZIP hash and model-cache
inventory. Transfer the cache directory and saved Docker image separately. Preserve
file permissions and verify transferred cache hashes against the sidecar. Checkpoint
and alignment redistribution terms must be reviewed before a public release.

## Prepare the VM

Load the saved image, unpack the verified transfer archive, and mount the transferred
cache and a persistent results directory. Use the same absolute container paths after
every restart. The examples below assume `/workspace/benchmark`, `/workspace/cache`,
and `/workspace/results` inside the container.

```bash
docker load -i helixflow-image.tar
docker run --rm --gpus all --network none --shm-size 16g \
  -v "$PWD/benchmark:/workspace/benchmark:ro" \
  -v "$PWD/cache:/workspace/cache:ro" \
  -v "$PWD/results:/workspace/results" \
  -e HELIXFLOW_LOCK_DIR=/workspace/results/gpu-locks \
  helixflow:experiment boltz-vm preflight /workspace/benchmark \
  --cache /workspace/cache --gpus 4 --output /workspace/results/preflight.json
```

Run all following commands inside the same image and mounts. Use a writable model
cache only if provisioning assets intentionally; timed experiments require a complete
cache and run with networking disabled. The preflight checks GPU count, a CUDA tensor
operation, current compute activity, lease availability, 20 GiB minimum free output
space, and a full cache hash inventory. Supply `--inventory` with the transfer sidecar
to verify that the model cache matches the local copy. Reserve additional space for
the entire study.

## Profile and fit on the target hardware

First run the six-case pilot. It has a two hour aggregate budget, 20 minute per-attempt
timeout, and stops after any failed or interrupted case:

```bash
boltz-vm profile /workspace/benchmark --cache /workspace/cache \
  --output /workspace/results/pilot
```

Inspect all profile JSON files, logs, structures, confidence files, and receipts. The
profiling journal preserves completed cases and elapsed budget across restarts. A failed
case requires inspection; use a new profiling output directory for an intentional rerun.

After the pilot, profile the entire corpus twice. Set an explicit total runtime ceiling
appropriate to measured pilot durations; this example permits up to 24 hours:

```bash
boltz-vm profile /workspace/benchmark --cache /workspace/cache --all --repeats 2 \
  --budget-seconds 86400 --timeout-seconds 3600 --output /workspace/results/profiling
boltz-profiles-to-csv /workspace/results/profiling/*-r*.json \
  --output /workspace/results/profiles.csv
boltz-train-predictor /workspace/results/profiles.csv --explicit-splits \
  --model /workspace/results/predictor.pkl --report /workspace/results/predictor-report.json \
  --plots /workspace/results/predictor-plots
```

Check held out runtime error and empirical quantile coverage. Review failures before
using the model: successful profiles alone can hide input sizes that do not fit. Keep
the frozen test split and chosen model parameters stable after this evaluation.

## Run matched trials

Copy `config/campaign.example.json` to a writable path and update benchmark, cache, and
model paths. The default 108-trial matrix is a configuration, not a command to rent or
provision hardware. Review its duration using the pilot measurements.

```bash
boltz-campaign plan /workspace/results/campaign.json --output /workspace/results/study
boltz-campaign run /workspace/results/study --limit 1
boltz-campaign status /workspace/results/study
boltz-campaign run /workspace/results/study
boltz-campaign report /workspace/results/study --output /workspace/results/study-report
```

The runner verifies code, Python package versions, workload, predictor, and manifests.
It checks required GPU capacity and a full model asset inventory. Trials execute in a
seeded random order. A new trial refuses active GPU compute processes; a resumed trial
reconciles its existing workers. Use a host isolated from unrelated GPU workloads.

SIGTERM/SIGINT requests a drain of the current trial and stops the outer runner. Pending
work remains persisted. Restart the same command to resume. Keep the image and mount
paths stable. Never replace GPU lock files while workers are active.

The report writes per-trial and per-owner CSV files, JSON accounting, and PNG/SVG plots.
Every failure remains visible. Read the trial rows beside mean curves; do not count
repetitions or the same biological targets as independent samples.

## Recovery checks and backup

Use fresh campaigns for controlled coordinator termination, worker termination,
timeouts, and retry tests. Check job identities and attempt histories after restart,
then validate the published artifact hashes. Keep failure experiments outside the
uninterrupted timing matrix.

Stop and drain the runner before copying the complete results directory. For a live
SQLite database use SQLite's backup API; copying only the database omits active WAL
state. Preserve the plan, index, attempts, input snapshots, receipts, telemetry, and
exported reports. Verify a copied transfer bundle and open several structures with an
independent parser. Confirm no workers remain before stopping the VM.
