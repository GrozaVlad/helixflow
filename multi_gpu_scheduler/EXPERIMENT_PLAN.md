# Pre VM experiment preparation

HelixFlow will be evaluated as a portable execution platform for Boltz jobs on a
single Linux host with multiple GPUs. The local preparation freezes the workload,
checks job accounting and recovery, and prepares a repeatable VM campaign. A four GPU
host is needed for the measured concurrency and scaling experiments.

## Questions and measurements

1. Does every accepted job reach an accounted terminal state, with readable published
   artifacts or an explicit failure reason?
2. How do throughput, initial waiting time, successful flow time, and worker occupancy
   change with one, two, and four GPUs?
3. How do FIFO, token size, predicted duration, researcher service, and the combined
   UAF policy affect these measurements for the same submitted jobs?
4. How much does the owner service term change per researcher service and slowdown?
5. How accurately do the runtime and memory estimates predict held out target groups?
6. Does interruption recovery preserve accepted jobs and publish one successful
   attempt per completed job?

Report accepted, successful, failed, and unschedulable counts beside timing statistics.
Worker occupancy measures elapsed worker time, while CUDA utilization comes from
sampled telemetry. Success only metrics exclude failures and must retain those counts.

## Frozen workload

The initial corpus contains 60 public PDB protein entities: 40 protein only jobs and
20 protein–ligand jobs. The residue bands are 100–249, 250–449, and 450–700. These are
single chain workloads; the ligand is a carbon-containing component from the same
deposition. Co-deposition does not establish pharmacological relevance to that chain.

The selection uses the first 500 sorted RCSB entities per length band, shuffled with a
fixed seed, canonical sequences, and distinct available Pfam annotations. This is a
convenience sample for software evaluation. Selection and exclusion records are kept
before any inference measurements. Original deposition DOIs, API responses, retrieval
dates, and source terms accompany the corpus.

Related targets are grouped by connected components of shared Pfam annotations or
global protein alignments. Alignment uses BLOSUM62, gap opening penalty 10, extension
penalty 0.5, at least 30% identical alignment columns, at least 80% paired residue
coverage of the longer sequence, and length ratio at least 0.8. This reduces related
sequence leakage but does not detect every remote homologue. Entire groups are assigned
to training, calibration, and test partitions with seed 42 and a 60/20/20 ratio.

Scientific settings are three recycling steps, 200 sampling steps, one diffusion
sample, and inference seed 42. The worker records the explicit seed in its command
and profile metadata. Each protein has a matching frozen A3M containing homologous
rows. MSA preparation precedes timing. Missing or mismatched alignments prevent
benchmark readiness.

The active `public-v1-heme-ccd` revision changes only the input representation of two
heme ligands from SMILES to cached CCD components after a preprocessing failure.
It retains all targets, groups, partitions, scientific settings, and MSA hashes, and
records its parent fingerprint. The original frozen corpus and failed pilot remain
available. All revised inputs passed the pinned Boltz parser on CPU before the new
pilot. CCD ligand features use actual cached heavy-atom counts, not one token per CCD.

Public sequences may be submitted to the ColabFold service in serial requests from
one IP. Tickets and downloaded archives are persisted; ambiguous submissions require
inspection before another request. Inputs, alignments, provenance, source records,
and partition definitions receive SHA-256 hashes. Runtime campaigns verify them.

RCSB API data use [CC0](https://www.rcsb.org/pages/usage-policy). The ColabFold
[usage guidance](https://github.com/sokrypton/ColabFold#faq) permits serial local queries.
Review the terms of constituent alignment databases before distributing the MSAs in a
public software release. A private research transfer package includes an explicit terms
review field. Model checkpoints retain their own terms.

## Predictor evaluation

Use the existing histogram gradient boosted quantile regressors for runtime p50,
runtime p90, and memory p90. Submission features include protein sizes, chain and ligand
counts, estimated tokens, MSA depth, input bytes, and inference settings.

Only training groups fit the regressors. Calibration groups supply maximum residuals
per group for upper quantile adjustment. At least nine independent calibration groups
are required for the explicit 90% calibration path. Report empirical coverage on held
out test groups; these small samples do not establish a universal coverage guarantee.
Neither actual durations nor test outcomes enter scheduling decisions.

Model artifacts record the feature schema, benchmark fingerprint, partition groups,
and GPU model. Fit and calibrate again on the VM hardware. Profiles from unlike GPU
models cannot be mixed by the current predictor. Failed and interrupted profiles remain
in execution accounting and are excluded from supervised positive-label training.

## Campaign matrix

The default matrix has 108 sequential trials: six policy variants, three GPU counts,
two arrival patterns, and three repetitions. Variants are FCFS, token SJF, predicted SJF,
least-served-owner FIFO, UAF-SJF, and UAF with owner service weight zero. The last is an
ablation of the combined policy. The live oracle is unavailable because it requires
future measured durations.

Each trial contains the same 12 held out targets for the current corpus, assigned to
four researcher identities. Saturated arrivals have 1 ms offsets to preserve the seeded
FIFO order and are all eligible before initial dispatch. Bursty arrivals
contain four jobs per burst at a fixed 60 second interval, with the same 1 ms tie break
inside each burst. Job order is shuffled per
repetition with a fixed seed and shared across compared variants. GPU count changes
capacity while preserving inputs, owners, forecasts, and arrival offsets.

Randomize trial order reproducibly. Run one trial at a time with one worker per selected
GPU. Freeze scientific settings, code, Python environment, model assets, and predictor.
Use one attempt per job for uninterrupted performance trials. Run controlled retry and
recovery scenarios separately. Preserve every failed job.

Keep individual trial measurements. Plots show repetition means and individual trials;
biological cases and repeated runs are not independent observations. Owner tables show
accepted jobs, successes, measured GPU service, and successful flow time. Scheduling
policy conclusions depend on this workload and arrival distribution.

## Local acceptance and VM handoff

Exercise four mock workers, all live policies, campaign interruption/resume, asset
tampering, group separation, timeout/retry accounting, and transfer integrity. Then run
six representative real cases sequentially, one per type and length band, with a total
two hour GPU budget and a maximum of 20 minutes per attempt. Stop after a failure and
retain diagnostics. The six profiles establish pipeline readiness; the VM profiles
provide the target hardware training and evaluation data.

The handoff includes an environment image, checksummed source and workload archive,
model cache inventory, GPU/CUDA preflight, profiling commands, campaign configuration,
backup instructions, and the report procedure in [VM_RUNBOOK.md](VM_RUNBOOK.md).

SoftwareX may describe the portable executor, algorithm, application, and observed
validation. The separate AWS managed architecture supports the software design. A
single four GPU VM measures execution within one host; managed AWS services and multiple
hosts require their own deployment evidence.
