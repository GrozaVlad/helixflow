# Local Boltz-2 Workbench

A self-contained local Boltz-2 2.2.1 installation with:

- GPU inference on NVIDIA CUDA through Docker
- FastAPI job service and browser UI
- asynchronous, single-GPU job queue
- embedded, locally hosted Mol* 3D structure viewer
- persistent model cache, inputs, logs, and prediction outputs
- YAML and legacy FASTA uploads

## What this project does

Local Boltz-2 Workbench is an end-to-end biomolecular structure prediction
application. It accepts YAML or FASTA inputs describing proteins and, when
using YAML, can also represent ligands, DNA, RNA, templates, constraints, and
binding-affinity requests.

After an input is uploaded through the browser, the FastAPI service creates a
background job and runs Boltz-2 inside a CUDA-enabled Docker container. When
automatic MSA generation is enabled, Boltz requests a multiple-sequence
alignment from the public ColabFold service. It then preprocesses the
biomolecular input and performs inference on the local NVIDIA GPU.

Each completed prediction can produce:

- a predicted three-dimensional structure in mmCIF (`.cif`) format
- overall, per-chain, and interface confidence scores
- pLDDT confidence values
- predicted aligned error (PAE)
- predicted distance error (PDE)
- binding-affinity results for supported protein-ligand inputs
- generated MSAs, processed inputs, and execution logs

The browser interface tracks queued, running, completed, and failed jobs.
Generated structures can be downloaded or inspected directly in the embedded
Mol* 3D viewer. Prediction artifacts remain on the local machine. When
automatic MSA generation is enabled, protein sequences are sent to the
configured ColabFold MSA service; disable that option and provide an MSA for a fully local run after
the model assets have been downloaded.

Model checkpoints and reference data are stored in a persistent host cache, so
they are downloaded only when needed. GPU jobs are serialized to prevent
concurrent predictions from competing for the same device and memory.

## Start without building (recommended)

Requirements: Linux AMD64/x86-64, Docker with Compose GPU support, a compatible
NVIDIA driver, and NVIDIA Container Toolkit. The image includes the CUDA/PyTorch
runtime; a separate host CUDA toolkit is not required. GPU memory requirements
depend on the input. The service is for trusted local use, not public hosting.

From this directory:

```bash
docker compose -f compose.prebuilt.yaml pull
docker compose -f compose.prebuilt.yaml up -d
```

This pulls `grozavlad/helixflow:local-setup`, the **browser application**
alias. The study/scheduler environment is available as
`grozavlad/helixflow:experimental-setup` and has an SSH-oriented entrypoint. The
prebuilt Compose file has no build step. `release/README.md` records the tested
image identity and validation, including a real API-submitted GPU prediction.
The dated browser tag `local-2026-11-16` and original study tag
`grozavlad/helixflow-vast:2026-10-29` remain available. Friendly aliases may receive
updates; use the digest in `release/README.md` for the exact tested browser image.

Only `compose.prebuilt.yaml` is needed to launch the image; a source checkout is
not required if that file is downloaded separately. The `cache/`, `data/inputs/`,
and `data/outputs/` directories are created beside it and persist on the host.
For an input example without a checkout:

```bash
docker compose -f compose.prebuilt.yaml cp boltz-local:/workspace/examples/estradiol_ESR1_long_fixed.yaml ./estradiol_ESR1_long_fixed.yaml
```

Open <http://127.0.0.1:8000>, choose the YAML, and enable automatic MSA generation
for that supplied input. This sends the protein sequence to the configured public
MSA service. Sensitive inputs require a compatible locally supplied alignment.
For example, a host file `data/inputs/alignments/protein.a3m` is visible inside the
container as `/workspace/data/inputs/alignments/protein.a3m`; reference that path
in the YAML and disable automatic MSA generation.

Stop and inspect logs with:

```bash
docker compose -f compose.prebuilt.yaml down
docker compose -f compose.prebuilt.yaml logs -f
```

Model checkpoints and reference assets are **not bundled** and download on the
first prediction. Keep sufficient disk space for the image, model cache, and job
outputs. Subsequent runs reuse the cache. Preserve the cache/output directories
when upgrading. Do not run the prebuilt and source-build Compose projects against
the same data directories at the same time. To change the port, prefix the startup
command with `BOLTZ_PORT=8080`.

## Build from source (optional)

```bash
./run.sh
```

Open <http://127.0.0.1:8000>. The first prediction downloads the Boltz
checkpoints and supporting data into `cache/`, so it takes longer and needs
internet access. MSA generation also contacts the public ColabFold service.

An example input is available at `examples/example.yaml`.

## Stop the source-build installation

```bash
./stop.sh
```

Stopping does not delete inputs, results, or model cache. To watch service
output:

```bash
docker compose logs -f
```

## Data

- `cache/`: model checkpoints and reference data
- `data/inputs/<job-id>/`: uploaded inputs
- `data/outputs/<job-id>/run.log`: Boltz output
- `data/outputs/<job-id>/predictions/`: structures and scores

The UI binds only to localhost. Override the port with, for example,
`BOLTZ_PORT=8080 ./run.sh`.

## GPU memory guidance

The defaults use one diffusion sample at a time and no dataloader subprocesses
to accommodate a broad range of consumer GPUs. Start with short, single-chain
proteins. Large complexes or long sequences require more GPU memory; reduce
sampling work or input size if a prediction runs out of memory.

YAML is preferred by upstream Boltz. With **Generate MSA** enabled, omit the
`msa` field. To run without the external MSA service, provide an `.a3m`/CSV MSA
or use `msa: empty` (lower accuracy).

