# HelixFlow public frozen benchmark workload

This archive contains the exact prepared workload used for the HelixFlow
multi-GPU scheduling study: 60 biological targets partitioned into 36 training,
12 calibration, and 12 test targets. It supplies inputs and frozen alignments,
not the full experiment outputs or a standalone installation of HelixFlow.
This public projection omits 322 cached RCSB responses containing unnecessary
third-party annotations. All 182 original non-cache files and the original
`frozen.json` are byte-identical to the experiment backup.

Software and experiment instructions: <https://github.com/GrozaVlad/helixflow>.

## Contents

- `inputs/`: 60 Boltz YAML inputs with relative `../msas/` references.
- `msas/`: 60 A3M alignments and their individual provenance records.
- `catalog.json` and `prepared.json`: target selection, source attribution,
  sequence metadata, split assignments, and input/alignment paths.
- `frozen.json`: unchanged SHA-256 inventory of the 504 original workload files.
- `public-release.json`: public file inventory, original frozen fingerprint, and
  explicit hashes of the 322 source-cache files omitted from this release.
- `DATA_NOTICE.md`: attribution, data-license conditions, and review outcome.
- `verify_public_bundle.py`: standalone integrity verification (Python 3.11+).

This is the `public-v1-heme-ccd` revision: two heme inputs use `ccd: HEM`
instead of SMILES. The revision retains the original targets, splits, and MSA
bytes. See the repository's `multi_gpu_scheduler/VM_RUNBOOK.md` for context.

## Verify and extract

Download `public-v1-heme-ccd-public.tar.gz` and its `SHA256SUMS` sidecar into the same
directory. Check the download before extracting:

```bash
sha256sum --check --ignore-missing SHA256SUMS
```

From the HelixFlow repository root, extract into a fresh destination. Do not
overwrite an existing workload or change its frozen inputs:

```bash
mkdir -p multi_gpu_scheduler/workloads
test ! -e multi_gpu_scheduler/workloads/public-v1-heme-ccd && \
  tar -xzf /path/to/public-v1-heme-ccd-public.tar.gz -C multi_gpu_scheduler/workloads
```

Verify every included file using Python 3.11+ (no GPU or dependencies required):

```bash
python3 multi_gpu_scheduler/workloads/public-v1-heme-ccd/verify_public_bundle.py
```

The verifier checks the unchanged original fingerprint and all included original
files, permits omissions only under `source-cache/*.json`, and rejects missing,
modified, or unexpected payload files. The public manifest covers this README,
the data notice, the verifier, and `frozen.json`; the archive checksum covers the
public manifest itself. Checksums are integrity checks, not digital signatures.
Keep results, Python bytecode, and other generated files outside the workload.

## Use with HelixFlow

Follow `multi_gpu_scheduler/EXPERIMENT_PLAN.md` and
`multi_gpu_scheduler/VM_RUNBOOK.md` in the repository, using this workload
directory instead of fetching or generating new MSAs. The published
`grozavlad/helixflow:experimental-setup` container provides the experimental
environment; use the recorded image digest when pinning a reproducible setup.

**Public-bundle support requires the updated scheduler checkout.** Previously
published container images expect all original cache files and are unchanged.
Use an updated source installation or overlay the updated source on the existing
image (from the repository root; no GPU needed for validation):

```bash
docker run --rm --network none --entrypoint python \
  -v "$PWD/multi_gpu_scheduler:/opt/multi_gpu_scheduler:ro" \
  -v "$PWD/multi_gpu_scheduler/workloads/public-v1-heme-ccd:/workspace/benchmark:ro" \
  -e PYTHONPATH=/opt/multi_gpu_scheduler -e PYTHONDONTWRITEBYTECODE=1 \
  grozavlad/helixflow:experimental-setup \
  -m experiments.benchmark validate /workspace/benchmark
```

Retain the source mount and environment variables when using that image for new
campaigns, together with the GPU/cache/results mounts in the runbook. This is an
explicit code update, not the unchanged historical software image; new campaign
provenance must record it. Do not use this bundle to resume historical campaigns
with modified code. No upstream cached metadata is needed for inference, but
source-data preparation or revision should use the complete original workload.

Inference additionally requires compatible NVIDIA hardware/drivers, separately
provisioned Boltz model assets, writable output storage, and the experiment
configuration. This archive includes no model weights, predictor pickle,
container image, credentials, or per-attempt scientific outputs. Refit the
runtime predictor on the execution hardware when evaluating a new host.

The frozen alignments allow inference without new MSA-server requests. They do
not guarantee bitwise-identical GPU outputs or identical timings across hosts.
Generating replacement MSAs is not an exact replay of the original workload.
The repository's selected evidence supports analysis of 108 trials and 1,296
successful job executions; it is distinct from this input archive.

## Provenance, attribution, and redistribution status

Target records include PDB identifiers, source URLs, structure publication DOIs
where available, retrieval metadata, and sequence-license references. Preserve
these records and cite the underlying structures and data resources when used.
PDB archive data and integrated third-party annotations are not necessarily
subject to identical terms; consult <https://www.rcsb.org/pages/policies>.

The alignments were retrieved through <https://api.colabfold.com> in `env` mode.
Each `.provenance.json` preserves the retrieval time, checksum, and server
metadata. The API did not report exact database versions. The frozen alignment
bytes and checksums identify what was used, but do not establish the exact
upstream database snapshot. ColabFold's public database history is background
information, not a verified per-job version record:
<https://github.com/sokrypton/ColabFold/wiki/MSA-Server-Database-History>.

The public-release review and attribution are documented in `DATA_NOTICE.md`.
The mixed-provider source cache is excluded. For the alignment adaptations,
follow CC BY-SA 4.0 conditions conservatively because ColabFold's paper and
download page differ on BY-SA versus BY. Underlying CC0 and CC BY rights remain
intact; HelixFlow's Apache-2.0 software license does not replace data licenses.
Historical `.provenance.json` files retain their preparation-time pending-review
wording to preserve original hashes; the release-level notice records the later
review. Database-version uncertainty remains a reproducibility limitation, not
a claim that exact upstream snapshots have now been identified.

No new biological or pharmacological validation is claimed by this workload.
It supports evaluation of software execution and scheduling, not clinical use.
