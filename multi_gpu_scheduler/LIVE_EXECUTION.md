# Live GPU execution and VM experiment preparation

The dispatcher runs trusted Boltz jobs on one Linux host with one or more NVIDIA GPUs.
SQLite stores the queue and attempt histories; each worker receives a GPU UUID and a
fresh output directory. The same interface runs on a workstation or a rented multi-GPU
VM. It is not a multi-node service or the managed AWS deployment.

## Supported workflow

1. Prepare protein or protein–ligand YAML inputs, with local matching A3M files.
2. Submit a manifest containing job IDs, researcher IDs, scientific settings, resource
   predictions, timeout, and retry limits.
3. Run one coordinator for that campaign. It selects compatible waiting jobs and launches
   at most one leased worker per GPU.
4. Export job accounting, performance records, profiles, and artifact locations.

The current release supports inline protein sequences and ligand SMILES/CCD codes.
Templates, external molecule files, DNA/RNA, and additional YAML fields are rejected
rather than incompletely copied. `msa: empty` is accepted explicitly; omission of an MSA
is rejected. Query matching is an input-integrity check, not validation of MSA quality.

CCD ligand features use the heavy-atom count from the configured Boltz molecular cache,
including repeated ligand chains and multi-component CCD entries. Missing components
are errors, not one-atom estimates. Feature extraction for CCD inputs therefore needs
the Boltz/RDKit environment. Use only trusted model/molecular caches: the upstream cached
RDKit molecules are pickle files. Never use an uploaded pickle as a molecular cache.
CPU-only mock manifests may supply `ccd_atom_counts` from the frozen benchmark catalog;
real submissions reject this override and inspect their configured cache instead.

## Environment

Use Linux, Docker Compose with NVIDIA GPU support, and sufficient writable disk space.
From `multi_gpu_scheduler`:

```bash
docker compose build scheduler
docker compose run --rm scheduler nvidia-smi
docker compose run --rm scheduler boltz-live --help
```

The base image is pinned by digest. `runtime-constraints.txt` pins Python dependencies to
the locally tested Boltz 2.2.1 / PyTorch 2.7.1 CUDA 12.8 environment. These constraints are
for the Python 3.11 container, not a generic host environment. The scheduler also supports
NumPy 1.26 because Boltz 2.2.1 requires NumPy below 2.

Model checkpoints and molecular assets must be provisioned in the mounted
`local_install/cache` before a timed experiment. Preserve them across campaigns. Build
and transfer images and prepare MSAs before starting paid GPU time where practical.
Record the final image ID/digest and software commit with the campaign evidence.

## Local functional run

The supplied smoke manifest uses the existing 149-residue example sequence, one recycling
step, ten sampling steps, one diffusion sample, and no MSA. Its two jobs are identical
inputs assigned to different owners. Resource predictions are manual placeholders, not
a trained model or independent benchmark samples.

```bash
docker compose run --rm scheduler boltz-live init /workspace/results/smoke \
  --policy uaf_sjf --cache /workspace/cache
docker compose run --rm scheduler boltz-live submit /workspace/results/smoke \
  /workspace/examples/live_smoke.json
docker compose run --rm scheduler boltz-live run /workspace/results/smoke
docker compose run --rm scheduler boltz-live export /workspace/results/smoke \
  --output /workspace/results/smoke/report
```

`init` discovers physical UUIDs and available framebuffer capacity through `nvidia-smi`,
not a marketing VRAM size. `--gpu-ids UUID1,UUID2` restricts a campaign to selected devices.
Use new campaign directories for each policy, repetition, or configuration.

Do not run predictions in the separate browser app at the same time. It does not share
these leases. The dispatcher skips GPUs already occupied by compute processes, but
cannot prevent an unrelated program from starting later.

For a CPU-only functional test, initialize with `--mock --mock-gpus 4` instead.
Mock workers create a labelled text artifact, not a structure. Reports identify mock
evidence, and the training-data converter rejects it.

## Reproducing a clean container installation

Run from the repository root (`boltz_aws_paper`) on a Linux Docker host with the
NVIDIA Container Toolkit and a compatible GPU driver. A fresh build needs internet
access for system/Python packages. This test reuses an already provisioned Boltz
model/molecular cache; it does not test first-time asset downloads. Do not run it
alongside another GPU workload. The browser app does not share scheduler GPU leases.

```bash
docker build --no-cache --progress plain -f multi_gpu_scheduler/Dockerfile \
  -t helixflow:clean-check .
docker image inspect helixflow:clean-check --format '{{.Id}}'
mkdir -p multi_gpu_scheduler/results/clean-check
docker run --rm --network none --gpus 'device=0' --shm-size 16g \
  -e OMP_NUM_THREADS=1 -e OPENBLAS_NUM_THREADS=1 \
  -v "$PWD/local_install/cache:/workspace/cache:ro" \
  -v "$PWD/multi_gpu_scheduler/results/clean-check:/workspace/check" \
  helixflow:clean-check bash -euc '
    python -m pip check
    boltz-live init /workspace/check/campaign --policy uaf_sjf --cache /workspace/cache
    boltz-live submit /workspace/check/campaign /opt/multi_gpu_scheduler/examples/live_smoke.json
    boltz-live run /workspace/check/campaign
    boltz-live export /workspace/check/campaign --output /workspace/check/report
  '
```

Use a new output directory for every rerun. Check the exported report for exactly
two succeeded jobs, no failed/unschedulable jobs, and readable structures. A zero
coordinator exit code alone does not establish job success. Retain the build log,
image identifier, package inventory, receipts and output hashes. The source is
installed inside the image, not mounted from a developer environment. This is a
reduced-step functional smoke test, not a new performance experiment or biological
accuracy assessment. A fresh build can differ from the archived study image because
not every transitive/system package is pinned; never silently replace that study image.

## Preparing real campaigns

Use `examples/live_smoke.json` as the manifest schema. Paths to inputs are resolved
relative to the manifest. Each input and its MSAs are copied to the campaign and hashed.
Submitting the same job ID again is rejected. A multi-job submission is transactional:
invalid entries reject the entire submission; staged but unaccepted files may remain
for diagnosis and are not queue entries.

`prediction` contains `runtime_p50_seconds`, `runtime_p90_seconds`, and `memory_p90_gib`.
Manual estimates are useful for initial profiling only. To use a fitted model:

```bash
docker compose run --rm scheduler boltz-live submit /workspace/results/campaign \
  /workspace/workloads/campaign.json --model /workspace/results/predictor.pkl
```

Only load trusted pickle files: loading an untrusted model can execute code.
The model hash is retained with each job. Keep test inputs and related biological
variants out of fitting and calibration; live submission does not enforce a research
train/test split for the user.

Optional manifest fields:

- `arrival_offset_seconds`: delay eligibility relative to the batch submission time.
- `max_attempts`: total attempts, including the first; default 1, maximum 10.
- `timeout_seconds`: attempt time limit; default 3600 seconds.
- `options`: positive `recycling_steps`, `sampling_steps`, and `diffusion_samples`.

`--watch` keeps a drained coordinator available for further submissions. Without it,
the coordinator exits when all accepted jobs are terminal.

## Policies and researcher accounting

Live policies are `fcfs`, `token_sjf`, `predicted_sjf`, `fair_service`, and `uaf_sjf`.
The oracle uses measured future duration and is only available in simulation.

`fair_service` selects the owner with the least accounted service, then uses FIFO.
It is a simple portable baseline, not a reproduction of AWS Batch fair-share.
UAF-SJF combines p90 duration with owner service lead and prioritizes compatible jobs
that have exceeded the aging threshold. `--fairness-weight 0` provides a no-service-
penalty ablation. No algorithm provides a hard waiting-time guarantee.

Service accounting includes completed attempt runtime and p90 reservations for active
attempts. A lost attempt without measured duration retains its reservation estimate,
which is reported as missing runtime evidence. Failed attempts still consume researcher
service. There are no administrator-assigned entitlements, hard time quotas, preemption,
or service decay in this release.

## Isolation and restart recovery

All campaigns sharing GPUs must share the same host lock directory. Compose sets
`HELIXFLOW_LOCK_DIR=/workspace/gpu-locks` and bind-mounts `results/gpu-locks`. Other
containers on that host must mount the same host directory at their configured lock path.
Do not delete or replace lock files while any coordinator or worker is running.
This is cooperative locking for trusted processes, not a security boundary.

The coordinator holds an exclusive campaign lock and persists claims before launching
workers. A worker and its Boltz child inherit the GPU lease. If the coordinator is killed,
a surviving worker continues; restarting the same campaign observes its lease or receipt
instead of immediately launching a duplicate. If the worker disappears without a receipt,
the attempt becomes `INTERRUPTED` after its lease is released. It is retried only within
the submitted attempt budget.

SIGINT/SIGTERM stops new dispatch and drains active attempts. Pending jobs remain queued.
Run the same command to resume them. A container forcibly stopped before draining kills
its workers; restart reconciliation records those incomplete attempts. Avoid short
container stop timeouts for normal draining.

Timeouts terminate the workload process group. Each attempt has a new directory; partial
outputs are never the published result. A successful Boltz exit must also produce
nonempty structure and readable confidence artifacts. The coordinator verifies recorded
output hashes before transactionally linking the successful attempt to the job.

Execution is retryable, not exactly-once computation. A workload whose successful work
was interrupted before receipt publication may be recomputed. The publication pointer
selects one successful attempt. Back up the complete campaign while quiescent, or use a
SQLite backup method; do not copy only `queue.sqlite3` while its WAL is active.

Keep container mount paths stable across restarts because snapshots and requests use
absolute paths. Run one container for the coordinator and workers; keep its result volume.

## Reports and model training

`boltz-live export` creates:

- `report.json`: settings, code hashes, package versions, jobs, attempts, and metrics.
- `summary.json`: counts, waiting/flow times, throughput, occupancy, and owner statistics.
- `jobs.csv`: per-job outcomes, retry counts, timing, and successful attempt references.
- `profiles/*.json`: measured attempt records accepted by `boltz-profiles-to-csv`.

Each attempt directory also contains `request.json`, `worker.json`, `receipt.json`,
`supervisor.log`, `run.log` for real Boltz jobs, `telemetry.json`, and `output/`.
Use `published_attempt` to find the completed structure for a job and open its mmCIF
in a compatible viewer. The browser app does not automatically list these campaigns.

Runtime includes worker startup, input verification, inference, and artifact checks.
Initial wait ends at first dispatch; successful flow includes retries. Worker occupancy
is not CUDA utilization. Device memory and utilization are sampled every 0.5 seconds
by default; brief peaks may be missed and other device activity can contaminate samples.
Runtime caches are fresh per attempt, while model assets persist. Keep this cache policy
fixed across comparisons.

Read success-only flow/fairness metrics alongside failed and unschedulable counts.
Do not train on mock records, smoke inputs, missing measurements, or mixed GPU types
without an explicit hardware-aware design.

```bash
docker compose run --rm scheduler bash -lc 'boltz-profiles-to-csv \
  /workspace/results/profiling/report/profiles/*.json \
  --output /workspace/results/profiles.csv'
```

The existing grouped cross-fitting tools evaluate predictors without sharing repeated
job IDs between training and test folds. They still require enough distinct biological
inputs and suitable grouping of related sequences.

## Four GPU pilot

On the rented host, first verify all four UUIDs and run the smoke example. Then profile
the curated distinct inputs on that hardware. The two local smoke repetitions do not
train a useful predictor.

For each matched arrival trace, run the five live policies with 1, 2, and 4 GPU UUIDs,
using separate campaign roots. Randomize policy order and repeat runs. Freeze inputs,
MSAs, predictor, sampling parameters, model assets, CPU/thread configuration, and cache
policy. Keep failures in the accounting. Perform controlled recovery tests separately
from uninterrupted performance trials.

```bash
boltz-compare-live results/fcfs/report/report.json \
  results/uaf/report/report.json --output results/comparison.csv
```

The comparator checks matched inputs, MSAs, owners, predictions, options, and arrival
offsets and refuses unfinished campaigns or mixed real/mock evidence. It does not
establish that hardware, cached models, or surrounding host load were identical;
check the captured provenance as well. `--allow-mock` is only for labelled functional
testing.

Before a paid campaign, agree on the distinct workload, repetitions, maximum runtime,
storage and shutdown policy. A single four-GPU host validates intra-node execution,
not multi-node scaling or the separate AWS-managed-service architecture.
