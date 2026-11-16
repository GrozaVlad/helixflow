# Pre VM validation on 21 October 2026

The preparation tools implement a public benchmark, biological group partitions,
explicit predictor evaluation, matched campaign planning and resumption, bounded
profiling, and a checksummed VM transfer archive. The experimental design is in
[EXPERIMENT_PLAN.md](EXPERIMENT_PLAN.md); operational commands are in
[VM_RUNBOOK.md](VM_RUNBOOK.md).

## Automated validation

All 51 tests passed on the Python 3.12 host and in the Python 3.11 container. The
container checks ran as UID 1000. Ruff and repository whitespace checks passed.

The new checks exercise sequence/family grouping, cross-partition rejection, exclusion
of test labels from fitting, GPU model mismatch rejection, calibration sample limits,
MSA query/width checks, server ticket resumption without another submission, campaign
resume across GPU counts, default matrix generation, manifest tampering, archive
inventory validation, and profiling stop/budget behavior. Existing execution tests
cover four mock workers, retries, process termination, GPU leases, and artifacts.

JUnit evidence for the corrected code is retained in
`results/prevm-validation-2026-10-21/pytest-ccd-fix.xml` and
`results/prevm-validation-2026-10-21/container-pytest-ccd-fix.xml`.
Earlier 47-test records remain alongside them. New regression checks cover cached CCD
heavy-atom counts, repeated/multi-component ligands, missing-component rejection,
durable mock CCD features, and revisions that leave the original corpus untouched.

The complete 108-trial matrix also passed with explicit synthetic mock fixtures:
1,296 accepted jobs, 1,296 successful mock jobs, and 1,296 attempts. The run resumed
after its first trial, compared matched manifests, and generated per-trial/per-owner
CSV files and labelled PNG/SVG figures. These counts establish functional orchestration;
the mock timings do not measure Boltz or GPU scaling. Evidence is retained in
`results/synthetic-functional-108-2026-10-21/report/`. Both figure layouts were inspected.

The same 108-trial matrix also completed on the actual public corpus before and after
the heme correction. The corrected run accounted for 1,296 successful mock jobs and no
failed jobs. Evidence is in `results/prevm-mock-ccd-2026-10-21/report/`; its labelled
mock timings are not Boltz performance measurements.

## Environment transfer

The corrected image tag is `boltz2-multi-gpu-scheduler:prevm-20261021-ccd`.
Its inspected image identifier is
`sha256:ac6147a13d7944c6ba477ad2fd53e6976b9047b2a75d46fe7ff541ad52c48b31`.
The base image is pinned, and runtime constraints include the resolved plotting
dependencies. The image build completed with `pip check` reporting no broken requirements.

The saved image is `results/handoff/helixflow-image-prevm-20261021-ccd.tar`. Its SHA-256 is
`460adc876feaeb45f0afd6bc0036aeb583d146269d41ed66869a2d2af8baf978`.
Use `docker tag boltz2-multi-gpu-scheduler:prevm-20261021-ccd helixflow:experiment` after
loading it to use the generic runbook commands.
The original image tag and `helixflow-image-prevm-20261021.tar` remain available for
the failed pilot's environment; neither was overwritten.

The container validation found and resolved a transfer packaging defect: bundled source
files and repository license/requirements files now have explicit locations in the
image. The archive validator also checks unexpected and duplicate entries.
MSA downloads now stream to disk with progress and a 180 second read timeout.
An interrupted transfer retains its partial file and never becomes a completed cache
entry; a dedicated test covers this failure boundary. The public endpoint does not
support HTTP byte ranges, so a later transfer retry fetches the same completed result
again without submitting a new alignment job.
Boltz inference uses explicit seed 42, retained in commands and profile metadata.
The real subprocess recovery test checks this seed in the successful worker command.

## Workload preparation

The public catalog contains 60 canonical protein sequences, 40 protein only jobs and
20 jobs with co-deposited ligands. Source API responses and exclusion reasons are
retained locally. Initial RDKit SMILES syntax checks passed for all 20 ligands, but
that check alone did not establish successful 3D conformer generation.

The fixed split contains 36 training, 12 calibration, and 12 test biological groups.
The alignment scoring and grouping criteria are recorded before profiling. The initial
match/mismatch scoring rule was rejected during preparation because it joined many
unrelated proteins through cheap gaps; the recorded BLOSUM62 and coverage rule replaces
it before benchmark freezing.

All 60 matching A3Ms are now available locally. The 58-target batch archive completed
at 85,417,278 bytes and passed gzip integrity checks. No MSA was regenerated for the
heme correction.

The original `public-v1` frozen inventory has SHA-256
`0e79ce1b0cb4c0481ea544505b79de66427ddf41237b2ec89111219f8927dbad`.
Its first real pilot succeeded on `10br_1`, then failed while creating a conformer
for the heme SMILES in `104m_1`. Boltz returned exit code zero after skipping that
input; the worker correctly rejected the missing structure and recorded failure.
That attempt, its logs and the original frozen inventory are preserved.

The new `public-v1-heme-ccd` frozen inventory has SHA-256
`186ffa519d122671429ccfb94f71af1c962577477e2d23daecd535f4367acf40`.
Only `prepared.json`, `inputs/104m_1.yaml`, and `inputs/1dt6_1.yaml` differ in the
inventory. Both heme inputs use the cached HEM CCD component. All 60 job identities,
sequences, partitions and MSA hashes remain identical. The revision records the
parent fingerprint, per-input before/after hashes and cached HEM asset hash.

All 60 revised inputs passed the pinned Boltz parser on CPU. HEM features now record
43 heavy atoms. The CPU evidence is
`results/prevm-validation-2026-10-21/cpu-input-validation-ccd.json`.

## Corrected single GPU pilot

All six preselected type/length cases succeeded with three recycling steps, 200
sampling steps, one diffusion sample and seed 42. Cached scientific assets and
benchmark files were read-only, networking was disabled, and runtime caches were
fresh for each attempt. Hardware was one RTX 5080 with 16,303 MiB reported memory.

| Target | Type | Residues | Worker seconds | Sampled peak GiB |
| --- | --- | ---: | ---: | ---: |
| 10br_1 | Protein | 204 | 20.78 | 9.13 |
| 104m_1 | Protein and HEM | 153 | 19.57 | 3.89 |
| 10ef_1 | Protein | 391 | 29.85 | 8.98 |
| 10ak_1 | Protein and ligand | 431 | 33.52 | 10.30 |
| 11eu_1 | Protein | 671 | 43.74 | 11.10 |
| 12vd_1 | Protein and ligand | 462 | 32.52 | 8.43 |

The corrected journal records 180.74 seconds, versus 87.93 seconds for the original
pilot including its failed attempt. The corrected run's budget was reduced to 7,112
seconds to retain the original aggregate two-hour ceiling. Each attempt retained a
20-minute timeout and stop-on-failure behavior.

An independent Gemmi parse verified all six mmCIFs, expected protein residue counts,
ligand atom counts and finite coordinates. The HEM output contains 43 ligand atoms,
including one iron atom. All staged-input and published-artifact hashes matched;
confidence JSON files parsed and contained finite confidence scores. Evidence is in
`results/prevm-validation-2026-10-21/independent-artifact-validation-ccd.json`.
Raw logs, structures, receipts, telemetry and the six-row `profiles.csv` are retained
under `results/prevm-pilot-ccd-2026-10-21/`.

These runs demonstrate successful software execution, not biological prediction
accuracy, representative runtime distributions or scheduler superiority. The desktop
display remained active, and the CPU mock campaign overlapped part of the pilot.
Memory values include the device baseline and may miss short peaks. Six local cases
are insufficient to fit the target VM predictor; physical multi-GPU measurements,
VM profiling/training and the measured policy campaign remain outstanding.
