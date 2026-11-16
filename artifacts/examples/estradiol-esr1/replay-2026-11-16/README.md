# Documented offline local example

This is a separate, seeded estradiol–ESR1 inference run, prepared on 16 November
2026 using the local workbench's Boltz image. It fills the historical example's
missing launch/timing record; it does **not** retroactively establish the settings
or timing of job `d5c2056a335a`. The parent directory's screenshot and prediction
still refer to that original job, not this new run.

`msa.csv` is the exact retained CSV from the historical job's
`boltz_results_estradiol_ESR1_long_fixed/msa/estradiol_ESR1_long_fixed_0.csv`.
Its first sequence is checked against the 253-residue protein in `input.yaml`.
The ligand SMILES is unchanged. The only scientific-input handling change is
binding the saved alignment explicitly instead of calling an MSA service.

## Evidence

The run completed successfully in **48.129 seconds** on an NVIDIA GeForce RTX
5080 (16 GB), using Boltz 2.2.1 and PyTorch 2.7.1+cu128. The frozen alignment has
3,348 rows. Settings include seed 42, three recycling steps, 200 sampling steps,
one structure sample, and five affinity samples. Both prediction stages reported
zero failures, with no MSA-mismatch warning. Gemmi read one model with 253 protein
residues, one ligand residue, and 2,037 atoms; coordinates and JSON scores were
finite. All 13 recorded checks passed. These are single-run operational results,
not a performance distribution or evidence of binding accuracy.

- `run-record.json`: hardware/software identity, complete command and CLI
  defaults, seed, input/model/cache hashes, timestamps, measured subprocess
  duration, output inventory, scores, and validation outcomes.
- `run.log`: unedited combined Boltz stdout/stderr.
- `expected/`: selected mmCIF and confidence/affinity JSON outputs from this run.
- `molecule-cache-sha256.json`: fingerprints of the extracted molecule cache;
  model weights and molecule assets themselves are not redistributed here.
- `SHA256SUMS`: integrity checks for the archived evidence.

The full generated `outputs/` directory remains local and is Git-ignored; its
inventory is retained in the run record. Only `expected/` is the portable output
subset, so those three files—not all intermediate paths in the record—are shipped
with the example. A metadata serialization error was corrected during preflight
before inference started; this record covers the sole completed inference run.

The timing starts immediately before launching the Boltz subprocess and ends
when it exits. It includes local preprocessing, model loading, structure and
affinity inference, and output writing. It excludes container startup, provenance
hashing, output validation, model downloads, and the historical MSA search. This
is a CLI execution measurement, not browser response time or a repeated benchmark.
GPU execution is seeded but bitwise equivalence across hardware and library
versions is not promised. Output checks do not establish biological accuracy or
drug efficacy.

## Reproduce without overwriting evidence

Build the local software image using `local_install/README.md`, or provide an
equivalent image with the versions recorded in `run-record.json`. The recorded
local image ID is a content identifier, not a publicly pullable registry digest.
Have a populated Boltz cache containing the two recorded checkpoints and `mols/`.

Create a fresh directory and copy **only** `input.yaml`, `msa.csv`, and
`reproduce.py` into it. Then replace both absolute host paths below:

```sh
docker run --rm --network none --gpus 'device=0' --shm-size 8g \
  -v /absolute/path/to/boltz-cache:/workspace/cache:ro \
  -v /absolute/path/to/fresh-example:/evidence \
  -w /evidence --entrypoint python \
  boltz2-local:2.2.1 /evidence/reproduce.py
```

The script refuses to run if `run-record.json` or `outputs/` already exists.
The image used here was
`sha256:c8669045912ba11f89b19a082adfc1c90c898e942db622adcf6310b4d6f464a3`.
The original execution explicitly passed this ID in `HELIXFLOW_IMAGE_ID` for
recording; when reproducing, record the image you actually use, not this ID.
The Docker network is disabled and the model cache is read-only.

Use `sha256sum -c SHA256SUMS` to verify the archived files. To inspect a fresh
structure, open `outputs/boltz_results_input/predictions/input/input_model_0.cif`
in Mol*. The original browser screenshot remains a separate demonstration.
