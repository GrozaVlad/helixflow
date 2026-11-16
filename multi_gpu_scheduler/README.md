# Controlled Multi-GPU Boltz Scheduler

This directory contains a live single-host GPU dispatcher and a fixed-capacity
experimental environment for the scheduling contribution.
It is separate from `local_install`, which is an interactive single-GPU application, and from
`aws_distributed`, which evaluates cloud elasticity, orchestration, storage, and recovery.

Accepted jobs are persisted in SQLite and retain their attempt histories. A campaign is valid
only after every job is accounted for as succeeded, failed, or unschedulable. Placement filters
predicted memory demand; a prediction does not guarantee that an inference will fit.

## Included components

- Boltz YAML/FASTA submission-time feature extraction.
- GPU-stage runtime and peak-VRAM profiling.
- Calibrated p50/p90 runtime and p90 VRAM prediction.
- FCFS, token-SJF, predicted-SJF, least-served-owner, uncertainty-aware fair SJF,
  and a simulation-only oracle baseline.
- A deterministic, non-preemptive multi-GPU trace simulator.
- Live subprocess workers with GPU UUID leases, persistent claims, bounded retries,
  timeouts, input snapshots, output hashes, telemetry, and restart reconciliation.
- CSV/JSON campaign reports and matched-workload comparison.
- Hardware profiles for a four-GPU `g6.12xlarge` and an editable university VM.

Large workloads, model files, and experimental results are intentionally excluded from Git.

See [the live execution runbook](LIVE_EXECUTION.md) for commands, recovery behavior, and
the distinction between mock-worker tests and real GPU evidence. The browser in
`local_install` is a separate application, not a front end for this dispatcher.
The [local validation record](VALIDATION.md) lists the tested environment, checks,
smoke measurements, and remaining VM experiments.
The live runbook also includes a [clean-container installation check](LIVE_EXECUTION.md#reproducing-a-clean-container-installation)
using the shipped example and a preprovisioned model cache.

## Local development

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev,experiment]'
ruff check scheduling experiments tests
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 pytest -q
```

## VM container

For a rented container without a full VM or nested Docker, see the
[Vast.ai image and deployment runbook](deploy/vast/README.md). It wraps the tested
experiment image with key-only SSH; workers remain native subprocesses.
The prebuilt study image is
[`grozavlad/helixflow-vast:2026-10-29`](https://hub.docker.com/r/grozavlad/helixflow-vast).
Use the [digest-pinned pull and verification commands](deploy/vast/README.md#use-the-published-image)
to reproduce that environment without rebuilding it. Scientific assets are not included.

From this directory, verify that Docker sees every GPU and build the pinned environment:

```bash
nvidia-smi
docker compose build
docker compose run --rm scheduler nvidia-smi
```

Place the curated, pre-MSA Boltz inputs under `workloads/`. The same immutable inputs and Boltz
configuration must be used for every policy. Profile each distinct job three times in randomized
order. The profiler measures the entire dispatched GPU process, including model startup:

```bash
docker compose run --rm scheduler boltz-profile-job \
  /workspace/workloads/example.yaml \
  --job-id example --gpu-index 0 --repeat 1 \
  --out-dir /workspace/results/raw/example-1 \
  --output /workspace/results/profiles/example-1.json
```

The profiler uses the same worker and validation as live execution. Every `--out-dir`
and `--output` must be new. Outputs live under `<out-dir>/output/`; logs, receipt, staged
input, and GPU samples live alongside that directory. MSAs must be local A3M files with a
matching query sequence, or explicitly `msa: empty` for a labelled single-sequence run.
No implicit MSA-server calls are made. Peak-memory labels now use sampled whole-device
memory rather than baseline-subtracted memory; do not mix older and newer profiling
definitions in one experiment.

Combine successful repetitions and train the calibrated quantile predictor:

```bash
docker compose run --rm scheduler bash -lc 'boltz-profiles-to-csv \
  /workspace/results/profiles/*.json \
  --output /workspace/results/profiles.csv'

docker compose run --rm scheduler boltz-train-predictor \
  /workspace/results/profiles.csv \
  --model /workspace/results/predictor.pkl \
  --report /workspace/results/training-report.json
```

For a functional shakedown, prepare a trace with the fitted deployment model:

```bash
docker compose run --rm scheduler boltz-prepare-simulation \
  /workspace/results/profiles.csv \
  --model /workspace/results/predictor.pkl \
  --output /workspace/results/trace.csv \
  --arrival poisson --rate 0.02 --owners 4 --seed 42

docker compose run --rm scheduler boltz-scheduler-simulate \
  /workspace/results/trace.csv --gpus 4 --gpu-memory-gib 24 \
  --output /workspace/results/simulation.json
```

For publication experiments, generate strictly out-of-fold predictions instead. The grouping key
is `job_id`, so all repetitions of one biological input remain in the same fold. Each fold trains
and conformally calibrates only on other jobs, and the report records the exact partition and
out-of-fold error/coverage:

```bash
docker compose run --rm scheduler boltz-crossfit-trace \
  /workspace/results/profiles.csv \
  --output /workspace/results/crossfit-trace.csv \
  --report /workspace/results/crossfit-report.json \
  --folds 5 --arrival poisson --rate 0.02 --owners 4 --seed 42

docker compose run --rm scheduler boltz-scheduler-simulate \
  /workspace/results/crossfit-trace.csv --gpus 4 --gpu-memory-gib 24 \
  --output /workspace/results/crossfit-simulation.json
```

The training portion of every fold must still contain at least ten distinct jobs. Use the
single-model trace only to check mechanics; do not use it for the reported policy comparison.

## Pre VM preparation

The benchmark and campaign tools prepare a frozen public workload and automate matched
policy comparisons. Start with [EXPERIMENT_PLAN.md](EXPERIMENT_PLAN.md) for the study
design and [VM_RUNBOOK.md](VM_RUNBOOK.md) for preparation, profiling, transfer, and
execution commands. `boltz-benchmark`, `boltz-campaign`, and `boltz-vm` provide these
workflows; install the `experiment` extra for alignment grouping and plotting.
The latest local evidence and transfer image identifiers are in
[PREVM_VALIDATION.md](PREVM_VALIDATION.md).
