# Local execution validation on 20 October 2026

The single-host dispatcher, shared profiling worker, and packaged CLI have been exercised
locally. This record establishes functional readiness for a four-GPU pilot, not a
multi-GPU performance result or a completed publication evaluation.

## Automated checks

The suite passed 38 tests in both environments:

- Host: Python 3.12 isolated development environment.
- Container: Python 3.11, NumPy 1.26.4, scikit-learn 1.6.1.

Checks cover feature extraction, predictor fitting and grouped traces, next-arrival
simulation, incompatible aged jobs, all five live policies, four concurrent mock
workers, accounting, shared GPU leases, duplicate submissions, MSA query validation,
input tampering, timeout/failure retries, coordinator restart, graceful draining,
worker termination, output integrity, and separation of mock and real evidence.

One subprocess test kills the supervisor while a fake Boltz child is alive. The
child retains its GPU lease until it exits; a replacement attempt starts afterward.
This verifies descriptor/process behavior, not GPU-driver recovery.

Ruff and `git diff --check` passed. The pinned image built successfully and `pip check`
reported no broken requirements.

## Packaged real GPU smoke run

Environment: one NVIDIA RTX 5080, 16,303 MiB reported framebuffer, driver 590.48.01;
Boltz 2.2.1 and PyTorch 2.7.1+cu128. This was a desktop with display activity, not an
isolated GPU server.

Image: `boltz2-multi-gpu-scheduler:0.1.0`

Validated image identifier:
`sha256:15a9b52bb70f19902cbae20824daf2b7b9b8482071e77cea060a59be81b0ee6a`

The installed CLI ran as UID 1000 with networking disabled and cached model assets.
The input was the 149-residue repository example in explicit single-sequence mode,
with one recycling step, ten sampling steps, and one diffusion sample. Both jobs used
the same sequence with different researcher IDs and manual resource estimates.

| Check | Observed result |
| --- | --- |
| Accepted jobs | 2 |
| Successful jobs | 2 |
| Failed or missing jobs | 0 |
| Attempts | 2 |
| Worker durations | 14.42 s and 14.40 s |
| Submission to final completion | 29.06 s |
| Maximum sampled whole-device memory | Approximately 3.55 GiB |
| GPU samples per attempt | 29 |
| Sampling errors | 0 |
| Output checks | Nonempty structures, confidence JSON, and verified output hashes |

An independent Gemmi parse of the two packaged-run mmCIF files found 1,161 atom
records in each. This confirms readable structural output, not prediction accuracy.

The standalone profiler also succeeded through the installed CLI: 14.43 s worker
duration and approximately 3.55 GiB maximum sampled whole-device memory.

These timings include startup and validation under reduced settings. They cannot
estimate representative Boltz workloads. Memory includes the desktop baseline and
may miss peaks between samples. The two jobs are not independent biological examples.
Neither scheduler superiority nor trained-model accuracy was evaluated.

## Local evidence paths

Raw artifacts remain outside Git:

- `results/packaged-validation-2026-10-20/report/report.json`
- `results/packaged-validation-2026-10-20/report/jobs.csv`
- `results/packaged-validation-2026-10-20/attempts/`
- `results/profile-validation-2026-10-20.json`
- `results/profile-validation-2026-10-20/`

The report includes per-job settings, scientific input hashes, package versions,
source hashes, GPU identity, attempt records, and successful artifact references.

Earlier diagnostic campaigns are preserved:

- `results/live-validation-2026-10-20`: non-root Numba cache permission failures.
- `results/live-validation-2026-10-20-r2`: non-root Triton cache permission failures.
- `results/live-validation-2026-10-20-r3`: successful run using the existing local
  Boltz image and mounted scheduler sources.

Workers now use writable, fresh runtime caches for each attempt. The first unpinned
image build was stopped when dependency resolution tried to upgrade PyTorch. The
final image uses the validated runtime constraints and the matching pinned base image.

## Remaining experiment work (historical, before the October 29–30 study)

1. Curate distinct, redistributable protein and ligand inputs with validated MSAs and
   fixed scientific settings. Do not use the smoke repetitions as training data.
2. Transfer the pinned environment, inputs, and model assets to the selected VM.
3. Confirm four physical GPUs, profile the workload there, and fit/evaluate predictions
   using disjoint biological groups.
4. Run matched, repeated policy comparisons with 1, 2, and 4 GPUs, including the
   least-served-owner baseline and fairness-weight ablation.
5. Run controlled failure tests on the VM and independently reproduce installation.

The browser app is not connected to this dispatcher. The implementation is
single-host with cooperative locks, bounded retryable computation, and no researcher
quotas or multi-node guarantees. AWS-managed-service deployment remains a reference
implementation, not a validated cloud experiment.

## Clean installation acceptance — 30 October 2026

The documented scheduler Dockerfile was rebuilt with `docker build --no-cache`
under a new tag, `helixflow-clean-install:2026-10-30`. The digest-pinned upstream
PyTorch base was reused; all subsequent installation layers were rebuilt, including
fresh APT/Python dependency installation. No existing scheduler image, developer
virtual environment, host-installed package, or mounted application source was
used to run the acceptance workload. This validates a clean container installation
from the current source tree, not an independent third-party clone or a clean OS.

- New local image identifier:
  `sha256:7add9ccaf8436f4e8ce07526e801a6b08ba2d121bf088b3364ad1f48eeca6f84`.
- Python package checks: `pip check` passed; all **11** installed command-line entry
  points accepted `--help`. The scheduler imported from `site-packages`.
- Core versions: Boltz 2.2.1, PyTorch 2.7.1+cu128, NumPy 1.26.4,
  scikit-learn 1.6.1, scheduler 0.1.0.
- A fresh container ran with **networking disabled**, one local NVIDIA GPU, 16 GiB
  shared memory, and existing model/molecular assets mounted **read-only**.
- CUDA BF16 arithmetic passed. Both jobs from the shipped `live_smoke.json`
  succeeded, with one attempt each and no failures or unschedulable jobs.
- All **22 output artifact hashes** independently verified; both mmCIF structures
  parsed with Gemmi and contained the expected 149 residues. Telemetry recorded
  no sampling errors. Campaign observed duration was 32.157 seconds.

These are two repetitions of the same reduced-step, single-sequence fixture,
not independent biological examples or additional scheduling performance evidence.
First-time checkpoint downloading, a new host-driver installation, and a second
person's reproduction were not tested. The rebuilt image is distinct from the
archived experimental image and does not replace it. Transitive and OS dependency
versions may differ; the complete fresh package inventory was retained.

Evidence (outside Git): `results/clean-install-20261030/` contains `build.log`,
`smoke-console.log`, `environment.json`, `pip-freeze.txt`, `validation.json`, the
validation script, and the complete campaign/report/output tree. Reproduction
commands are in [the live runbook](LIVE_EXECUTION.md#reproducing-a-clean-container-installation).
The fresh test container exited and was removed automatically; its output evidence
and image remain. Existing application containers and remote study results were
not changed. The full 108-trial performance comparison completed and was backed up
separately. The subsequent recovery checks are recorded below.

## Real-process recovery acceptance — 30 October 2026

Four isolated campaigns ran on the existing four-GPU rental using the unchanged
study image/application code. No fault was injected into the performance campaigns.
The fixture was the shipped 149-residue protein with explicit empty MSA, three
recycles, 200 sampling steps, one diffusion sample and seed 42. Resource predictions
were conservative manual test values, not additional predictor-validation evidence.

| Scenario | Injected condition | Observed result |
| --- | --- | --- |
| Coordinator crash | SIGKILL after four workers had CUDA contexts on distinct GPUs; restart coordinator | All four original attempts succeeded; worker leases survived; no duplicate attempts/publications |
| Worker-supervisor crash | SIGKILL supervisor while its Boltz child ran; allow child to finish | Child retained GPU lease; original attempt recorded INTERRUPTED without a receipt; one retry succeeded; only retry result published |
| Timeout | One-second timeout, one permitted attempt; healthy job queued behind it | Timeout recorded FAILED in 1.064 seconds; healthy job succeeded afterward |
| Retry exhaustion | One-second timeout, two permitted attempts; healthy job queued behind it | Exactly two timed-out attempts, final FAILED state, no published result; healthy job succeeded afterward |

The successful suite took 207.969 seconds. It accounted for nine jobs and eleven
attempts: seven jobs succeeded and two intentionally failed. The worker-crash retry
was dispatched 14.327 seconds after injection, after the surviving child's lease
was released; final success was observed 53.921 seconds after injection. The lost
attempt's runtime is explicitly missing, with reservation-based accounting retained.
These timings describe individual acceptance cases, not recovery-time guarantees.

After every case, all GPUs were idle and the configured GPU leases could be
acquired and released. Rerunning each drained coordinator created no new attempts.
All seven published structures parsed with 149 residues; **77 artifact hashes**
verified both remotely and independently after download. The two failed jobs had
no published result. This demonstrates bounded retry/reconciliation and single
successful-result publication in these cases, not exactly-once computation.

Two initial harness diagnostics are retained: the first used NVIDIA host PIDs to
identify container processes and missed its injection window; the second found
that this Python build lacked `os.pidfd_open`. Neither injected a crash. The final
harness used GPU UUIDs for readiness and Linux pidfd syscalls (preflight-tested)
for process-identity-safe signals. No installed scheduler code was changed.

Evidence: `results/vast-58269544/remote-results/phase-5-recovery-r3/`, adjacent
`phase5-r3-console.log`, the recorded `phase5_recovery.py` runner, and
`recovery-backup-audit.json`. Earlier diagnostics are in `phase-5-recovery/` and
`phase-5-recovery-r2/`. All three result trees and logs were downloaded; checksum-only
rsync found no differences across 1,430 regular files (37,341,726 bytes).

Scope limits: one execution per fault scenario; timeouts during process startup,
not a stalled CUDA kernel; no machine/container loss, disk corruption, or multi-node
recovery. The provider instance was left allocated but idle after verification.
