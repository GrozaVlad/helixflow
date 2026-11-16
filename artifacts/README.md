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

`release-assets/public-v1-heme-ccd.tar.gz` is a **locally staged, Git-ignored** archive
of the exact frozen inputs, 60 MSAs, their provenance and source metadata cache.
All 504 files in its frozen manifest were hash-verified during migration. Its checksum is recorded
in `import-manifest.json`. It is not yet published, and must undergo redistribution
review before being uploaded as a release asset or to an archival repository.

After obtaining the archive, extract it under `multi_gpu_scheduler/workloads/`:

```bash
tar -xzf artifacts/release-assets/public-v1-heme-ccd.tar.gz -C multi_gpu_scheduler/workloads/
```

Then follow `multi_gpu_scheduler/EXPERIMENT_PLAN.md` and `VM_RUNBOOK.md`, configuring
paths for the new host. The full campaign requires GPUs, separately provisioned
Boltz models and compatible software. Downloading new MSAs is not an exact replay
of the frozen experiment. The lightweight YAML subset alone cannot run with its
MSA references unresolved.

The full per-attempt scientific outputs, logs, telemetry and original deployment
backups remain in the original private project. Selected evidence here supports
figure reproduction, but does not replace publication of a curated full evidence
archive where required. Do not publish model caches or assume Apache-2.0 applies
to upstream biological databases or third-party data.

The architecture figures are code-generated explanatory diagrams. AWS is an
unvalidated reference backend; the local runner diagram distinguishes the browser
workbench from the multi-GPU CLI. AI assistance with software, analysis and figure
source code must be disclosed accurately in the accompanying article.
