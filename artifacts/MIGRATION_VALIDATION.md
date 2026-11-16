# Local migration validation — 16 November 2026

The original project was copied selectively into this new repository; no original
files were removed and no old Git history, manuscript, credentials, model caches,
runtime caches, predictor pickle or Terraform state was intentionally included.

Checks performed:

- 222 selected source/artifact files hash-checked immediately after copying.
- 51 scheduler tests passed using packages installed from this repository.
- 12 AWS unit tests passed; these used no live AWS deployment.
- Scheduler and AWS Ruff checks passed.
- Import paths confirmed both packages resolve to the new repository.
- Bundled evidence hashes passed; trial accounting verifies 108 trials and 1,296
  successful jobs, with 24 held-out predictor observations.
- Relocated evidence extraction reproduced the original compact snapshot exactly.
- All 504 frozen-manifest entries passed SHA-256 checks inside the separately staged
  workload archive. The archive is Git-ignored and not publicly hosted yet.
- Targeted AWS/GitHub token and private-key signature scan found no matches. This
  heuristic is not a comprehensive security or privacy audit.
- Git candidate inventory excluded manuscript files, archives, virtual environments,
  Terraform state and known secret-file patterns.

The isolated development environment uses currently resolved dependencies within
the declared ranges, not necessarily the study's pinned inference environment.
No GPU predictions, cloud infrastructure deployment, new performance measurement,
commit, push or public release were performed in this migration.

Full raw attempt outputs remain in the original project. Licensing, scientific-data
redistribution, complete evidence publication and release metadata remain subject
to the root release checklist. Pre-rendered result figures were copied unchanged;
no scientific values were edited.
