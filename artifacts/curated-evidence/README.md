# HelixFlow curated experimental evidence

This bundle supports independent inspection of the HelixFlow scheduling study.
It contains original measurement records, not a resumable VM backup and not the
frozen-MSA workload. Software: <https://github.com/GrozaVlad/helixflow>.

## Included evidence

- `remote-results/phase-4-comparison/`: configurations, plan, index, manifests,
  all 108 trial reports, all 1,296 job/attempt records, receipts, telemetry,
  logs, input YAML snapshots, and prediction confidence JSON files.
- `remote-results/phase-2-profiling/`: 120 profiles (60 targets, two repeats),
  predictor evaluation, training table, held-out predictions, and underlying
  execution records. The serialized predictor is deliberately excluded.
- `remote-results/phase-3-concurrency/`: concurrency validation and measurements.
- `remote-results/phase-5-recovery-r3/`: the final four recovery scenarios,
  including expected failures, retry histories, and event records.
- `remote-results/pilot/`: pilot measurements and execution records.
- `selected-evidence/`: the small evidence collection also distributed in GitHub,
  including clean-install validation and historical backup audits.
- Representative structures and prediction arrays: **all 12 jobs from
  `phase-4-comparison/study/trials/burst-r1-g4-uaf_sjf`**. This is a fixed example
  trial, not a selection of the best predictions and not a biological benchmark.
  Its `output/.../predictions/` directories contain CIF/NPZ prediction files;
  confidence JSON files are retained across all included phases.
- `MANIFEST.json`: SHA-256 hashes and byte sizes for every bundled payload file,
  source categories, selection rules, exclusions, and source-output audit results.

Original records are copied byte-for-byte. Absolute paths, process IDs, GPU
identifiers, and timestamps describe the historical execution environment;
they are not portable commands. Runtime caches, repeated MSAs, processed model
intermediates, model/predictor pickle files, SQLite/WAL state, lock files, and
superseded recovery-development runs are not bundled. No SSH configuration or
deployment-session notes are included. Input YAML references may therefore point
to omitted alignments. Use the separate frozen workload for inference reruns.

## Verify the download and evidence

Download the archive and its `SHA256SUMS` sidecar. In that directory:

```bash
sha256sum --check --ignore-missing SHA256SUMS
tar -xzf helixflow-curated-evidence.tar.gz
python3 helixflow-curated-evidence/verify_evidence.py
```

The verifier needs only Python 3.11+ and no GPU/network. It checks the complete
payload inventory, original plan/index/report linkage, all 108 completed trials
and 1,296 successful comparison jobs, receipt agreement, checksums of included
receipt-listed outputs, profiling coverage, held-out prediction count, and final
recovery accounting (9 jobs, 11 attempts, 7 successful jobs and 2 expected failures).

Receipts also list outputs deliberately omitted from this bundle. The verifier
reports included versus omitted outputs; it does **not** claim to reverify absent
files. During packaging, all 15,552 comparison output hashes and all 77 successful
recovery output hashes are checked against the retained original backup, before
curation. This build-time check is recorded separately in `MANIFEST.json`.

To reproduce the published plots, use the matching GitHub repository's
`artifacts/verify_artifacts.py` and `artifacts/generate_results.py --refresh-evidence`.
Its selected source evidence is also included here for cross-checking. The full
trial reports provide job-level observations beyond those aggregate plots.
The archive is not intended to resume campaigns: exported JSON reports replace
the omitted live queue databases for analysis.

## Interpretation and scope

The comparison comprises six policies, 1/2/4 GPUs, two arrival patterns, and
three repetitions per configuration on one four-RTX-4090 host. The same 12 held-out
biological targets recur across trials; 1,296 executions are not 1,296 independent
biological samples. Repetition ranges are descriptive, not confidence intervals.
Profiling, pilot, and recovery runs are separate from the uninterrupted comparison.
Recovery tests concern processes, not whole-host loss. AWS is an unvalidated
reference implementation, not the environment measured here.

No new inference was run to create this bundle. Scientific outputs are predictions,
not experimentally validated binding or clinical conclusions. Exact timings are
hardware/environment dependent. Complete reruns require the separate frozen input
archive, compatible hardware/software, and separately provisioned model assets.

## Attribution and publication scope

Please cite the HelixFlow article when available and the software repository.
Preserve biological source attribution in the workload catalog when using its
targets. This evidence bundle excludes third-party MSA sequences and source-cache
database records. The separate public input bundle also excludes mixed-provider
cached metadata and provides its own `DATA_NOTICE.md` for alignment/data licenses.
No blanket relicensing of
upstream software, models, or biological resources is asserted by this README.

`MANIFEST.json` is outside its own hash inventory; the external archive checksum
covers it. Checksums detect changes, but are not digital signatures or proof of
experimental correctness. Pattern-based secret scanning is a precaution, not a
guarantee that arbitrary sensitive content can be detected.
