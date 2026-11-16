# Reproducibility artifacts

This directory contains supporting materials, not the manuscript or Overleaf project.

- `results/measurements.json`: portable snapshot of 108 trial summaries, 24 held-out
  predictor observations, and operational checks, with source hashes.
- `evidence/`: original comparison reports, profiling records, held-out predictions,
  recovery summaries, clean-install validation, and backup audits. These are selected
  records, **not the full raw attempt archive**.
- `workloads/public-v1-heme-ccd/`: 60 input YAML files, catalog, prepared metadata and
  frozen hashes. MSA paths intentionally retain their relative `../msas/` references.
- `generate_results.py`, `requirements.txt`: reproducible Matplotlib analysis.
- `figures/`: three measured plots (PDF/PNG/SVG), overview exports, and historical
  architecture TikZ sources retained for reference.
- `diagrams/`: authoritative editable draw.io sources and exports for the general
  overview, local execution, and AWS architecture. The overview connects enclosing
  input, execution, and output panels rather than individual aligned cards.
- `generate_architecture.py`: exports the existing draw.io files to PDF/SVG/PNG
  using draw.io Desktop, preserving manual source edits. Run
  `python artifacts/generate_architecture.py --drawio /path/to/drawio`.
- `generate_system_drawio.py`, `generate_aws_drawio.py`: optional source generators;
  these reset diagram edits and should not be used merely to export edited artwork.
- `import-manifest.json`: original source commit and byte-level import provenance.
- `verify_artifacts.py`: verifies source hashes, trial accounting, and frozen input hashes.

## Reproduce analysis without GPUs

From the repository root:

```bash
python3 artifacts/verify_artifacts.py
python3 -m venv .venv
.venv/bin/pip install -r artifacts/requirements.txt
.venv/bin/python artifacts/generate_results.py --refresh-evidence
```

The refresh option reconstructs the compact snapshot from `evidence/`; it does not
contact the old rental host. Plots use repetition means/ranges, not confidence
intervals. See the source for the precise metric calculations. Historical absolute
paths in original evidence describe the measurement environment and are not portable
commands. No predictor pickle is distributed: train from the profiling records using
the scheduler tools rather than loading an untrusted serialized model.

## Exact inference reruns require additional assets

`release-assets/public-v1-heme-ccd-public.tar.gz` is the **locally staged,
Git-ignored public input archive**. It retains all 60 inputs, 60 MSAs, provenance,
catalog, splits, and the original `frozen.json` without changing their bytes.
It omits the 322 mixed-provider source-cache responses, not scientific inputs.
All 504 original frozen files were checked before packaging; the public inventory
explicitly identifies the omitted cache paths/hashes. See `public-workload-release.json`.

The archive includes a [workload README](workloads/public-v1-heme-ccd/README.md)
with extraction, public-inventory verification, usage, and provenance limitations.
The [data notice](workloads/public-v1-heme-ccd/DATA_NOTICE.md) records the review,
attribution, and conservative CC BY-SA treatment of alignment adaptations. No
blanket Apache-2.0 license is applied to third-party data. The complete original
archive is retained under `release-assets/private-backups/` and is **not for upload**.

After obtaining the archive, extract it under `multi_gpu_scheduler/workloads/`:

```bash
mkdir -p multi_gpu_scheduler/workloads
test ! -e multi_gpu_scheduler/workloads/public-v1-heme-ccd && \
  tar -xzf artifacts/release-assets/public-v1-heme-ccd-public.tar.gz -C multi_gpu_scheduler/workloads/
python3 multi_gpu_scheduler/workloads/public-v1-heme-ccd/verify_public_bundle.py
```

Then follow `multi_gpu_scheduler/EXPERIMENT_PLAN.md` and `VM_RUNBOOK.md`, configuring
paths for the new host. The full campaign requires GPUs, separately provisioned
Boltz models and compatible software. Downloading new MSAs is not an exact replay
of the frozen experiment. The lightweight YAML subset alone cannot run with its
MSA references unresolved. Public projections require the updated scheduler;
the workload README documents the source overlay for previously published images.
Keep the read-only workload separate from generated output. The original frozen
fingerprint is preserved; new runs still record their updated software provenance.

Rebuild the public input package from the retained complete archive with:

```bash
python3 artifacts/build_public_workload.py \
  --source artifacts/release-assets/private-backups/public-v1-heme-ccd.full.tar.gz \
  --output /path/to/fresh-release-directory
```

## Curated execution evidence

`release-assets/helixflow-curated-evidence.tar.gz` is a separately staged,
Git-ignored release attachment. It includes original per-job/trial reports,
receipts, telemetry, logs, configurations, profiling, final recovery evidence,
and representative predictions from one fixed 12-job trial. It excludes repeated
MSAs, runtime caches, serialized models, processed intermediates, live queue
databases, and superseded recovery-development runs. It is not a resumable VM
backup or a complete collection of every scientific prediction output.

See [the evidence README](curated-evidence/README.md) for the exact scope and
verification instructions. The archive includes a standalone Python verifier
and per-file hash manifest. `release-assets/curated-evidence-validation.json`
records packaging checks; `release-assets/SHA256SUMS` covers both release archives.
The public input archive has its own data notice; neither archive contains the
mixed-provider source cache. Use the updated shared checksum file.

The release attachments are **only** `public-v1-heme-ccd-public.tar.gz`,
`helixflow-curated-evidence.tar.gz`, and `SHA256SUMS`. Do not attach private backups.

To reproduce the packaging from the retained original experiment backup:

```bash
python3 artifacts/build_curated_evidence.py --source /path/to/vast-58269544 --dry-run
python3 artifacts/build_curated_evidence.py --source /path/to/vast-58269544 --output /path/to/fresh-release-directory
```

The builder scans selected text for common credential patterns, verifies all
15,552 comparison and 77 successful recovery output hashes against the backup,
copies selected original records without modification, validates the bundle, and
refuses to overwrite an existing evidence archive. The original full backup is
retained privately. Do not publish model caches or assume Apache-2.0 applies to
upstream biological databases or third-party data.

The architecture figures are code-generated explanatory diagrams. AWS is an
unvalidated reference backend; the local runner diagram distinguishes the browser
workbench from the multi-GPU CLI. AI assistance with software, analysis and figure
source code must be disclosed accurately in the accompanying article.
