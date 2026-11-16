"""Public PDB workload preparation. Network access occurs only in explicit fetch/MSA commands."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import random
import re
import shutil
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import yaml

from scheduling.live_store import atomic_json, digest

OPTIONS = {"recycling_steps": 3, "sampling_steps": 200, "diffusion_samples": 1}
BANDS = [(100, 249, 13, 7), (250, 449, 13, 7), (450, 700, 14, 6)]
API = "https://data.rcsb.org/rest/v1/core"
MSA_SERVER = "https://api.colabfold.com"


def request(url, data=None):
    headers = {"User-Agent": "HelixFlow-academic-benchmark/0.1"}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        data = urllib.parse.urlencode(data).encode()
    for attempt in range(3):
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, data=data, headers=headers), timeout=45
            ) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError) as error:
            # POST may already have submitted work; preserve its ambiguity for the caller.
            if (
                data is not None
                or attempt == 2
                or (isinstance(error, urllib.error.HTTPError) and error.code < 500)
            ):
                raise
            time.sleep(2**attempt)


def cached_json(root, url):
    folder = root / "source-cache"
    folder.mkdir(exist_ok=True)
    target = folder / (hashlib.sha256(url.encode()).hexdigest() + ".json")
    if not target.exists():
        payload = json.loads(request(url))
        atomic_json(target, payload)
        time.sleep(0.35)  # Single process, below a handful of API queries/second.
    return json.loads(target.read_text())


def download_archive(url, destination, *, timeout=180):
    """Stream a completed result; retain failed partial attempts for diagnosis.

    The public server does not implement HTTP byte ranges. A later invocation
    therefore starts a fresh transfer of the same result, never another MSA job.
    """
    if destination.exists():
        return
    partial = destination.with_name(destination.name + f".part-{time.time_ns()}")
    received, reported = 0, time.monotonic()
    request_object = urllib.request.Request(
        url, headers={"User-Agent": "HelixFlow-academic-benchmark/0.1"}
    )
    print(f"Downloading completed MSA result to {partial}", flush=True)
    try:
        with (
            urllib.request.urlopen(request_object, timeout=timeout) as response,
            partial.open("xb") as handle,
        ):
            while chunk := response.read1(64 * 1024):
                received += len(chunk)
                if received > 1024**3:
                    raise ValueError("MSA archive exceeds 1 GiB transfer limit")
                handle.write(chunk)
                if time.monotonic() - reported >= 10:
                    handle.flush()
                    print(f"MSA archive: {received / 1024**2:.2f} MiB received", flush=True)
                    reported = time.monotonic()
            handle.flush()
            os.fsync(handle.fileno())
        partial.replace(destination)
        print(f"MSA archive downloaded: {received} bytes", flush=True)
    except Exception:
        print(
            f"Transfer incomplete; retained {partial}. Resume the same ticket to retry.", flush=True
        )
        raise


def validate_a3m(text, sequence):
    records = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(">"):
            records.append("")
        elif not records or not re.fullmatch(r"[A-Za-z.-]+", line):
            raise ValueError("invalid A3M record")
        else:
            records[-1] += line
    if not records or re.sub(r"[a-z.-]", "", records[0]) != sequence:
        raise ValueError("MSA query does not match sequence")
    if any(len(re.sub(r"[a-z.]", "", row)) != len(sequence) for row in records):
        raise ValueError("MSA aligned widths differ from query")
    if len(set(records)) < 2:
        raise ValueError("MSA-backed benchmark requires at least one non-query row")
    return len(records)


def fetch(root):
    """Select by frozen length/type criteria, never inference outcomes."""
    root.mkdir(parents=True, exist_ok=True)
    catalog_path = root / "catalog.json"
    if catalog_path.exists():
        raise ValueError("catalog already exists; retain it or use a new benchmark directory")
    selected, exclusions = [], []
    sequences = set()
    family_ids = set()
    for lower, upper, protein_quota, ligand_quota in BANDS:
        query = {
            "query": {
                "type": "group",
                "logical_operator": "and",
                "nodes": [
                    {
                        "type": "terminal",
                        "service": "text",
                        "parameters": {
                            "attribute": "entity_poly.rcsb_sample_sequence_length",
                            "operator": "range",
                            "value": {"from": lower, "to": upper},
                        },
                    },
                    {
                        "type": "terminal",
                        "service": "text",
                        "parameters": {
                            "attribute": "entity_poly.rcsb_entity_polymer_type",
                            "operator": "exact_match",
                            "value": "Protein",
                        },
                    },
                    {
                        "type": "terminal",
                        "service": "text",
                        "parameters": {
                            "attribute": "rcsb_entry_info.polymer_entity_count_protein",
                            "operator": "equals",
                            "value": 1,
                        },
                    },
                ],
            },
            "return_type": "polymer_entity",
            "request_options": {
                "paginate": {"start": 0, "rows": 500},
                "sort": [{"sort_by": "rcsb_id", "direction": "asc"}],
            },
        }
        url = "https://search.rcsb.org/rcsbsearch/v2/query?" + urllib.parse.urlencode(
            {"json": json.dumps(query)}
        )
        candidates = [r["identifier"] for r in cached_json(root, url)["result_set"]]
        random.Random(42 + lower).shuffle(candidates)
        counts = {"monomer": 0, "protein_ligand": 0}
        for identifier in candidates:
            if counts == {"monomer": protein_quota, "protein_ligand": ligand_quota}:
                break
            pdb, entity = identifier.split("_")
            try:
                source = cached_json(root, f"{API}/polymer_entity/{pdb}/{entity}")
                sequence = source["entity_poly"]["pdbx_seq_one_letter_code_can"].replace("\n", "")
                if not lower <= len(sequence) <= upper or not re.fullmatch(
                    r"[ACDEFGHIKLMNPQRSTVWY]+", sequence
                ):
                    raise ValueError("noncanonical sequence or length outside band")
                families = {
                    a["annotation_id"]
                    for a in source.get("rcsb_polymer_entity_annotation", [])
                    if a["type"] == "Pfam"
                }
                if not families:
                    raise ValueError("missing family annotation")
                if sequence in sequences or families & family_ids:
                    raise ValueError("duplicate sequence or already represented Pfam family")
                entry = cached_json(root, f"{API}/entry/{pdb}")
                ligand = None
                if counts["protein_ligand"] < ligand_quota:
                    for number in entry["rcsb_entry_container_identifiers"].get(
                        "non_polymer_entity_ids", []
                    ):
                        component = cached_json(root, f"{API}/nonpolymer_entity/{pdb}/{number}")
                        code = component["pdbx_entity_nonpoly"]["comp_id"]
                        chem = cached_json(root, f"{API}/chemcomp/{code}")
                        formula = chem["chem_comp"].get("formula", "")
                        atoms = chem.get("rcsb_chem_comp_info", {}).get("atom_count_heavy", 0)
                        smiles = chem.get("rcsb_chem_comp_descriptor", {}).get("SMILES_stereo")
                        if 8 <= atoms <= 60 and re.search(r"\bC(?:\d|\s|$)", formula) and smiles:
                            ligand = {
                                "ccd": code,
                                "smiles": smiles,
                                "heavy_atoms": atoms,
                                "source": f"{API}/chemcomp/{code}",
                            }
                            break
                kind = "protein_ligand" if ligand else "monomer"
                if counts[kind] >= (ligand_quota if ligand else protein_quota):
                    raise ValueError("type quota filled or no suitable co-deposited organic ligand")
                record = {
                    "job_id": identifier.lower(),
                    "pdb_id": pdb,
                    "entity_id": entity,
                    "sequence": sequence,
                    "families": sorted(families),
                    "job_type": kind,
                    "length_band": [lower, upper],
                    "ligand": ligand,
                    "source": f"{API}/polymer_entity/{pdb}/{entity}",
                    "structure_doi": f"https://doi.org/10.2210/pdb{pdb.lower()}/pdb",
                    "retrieved_at": datetime.now(UTC).isoformat(),
                    "sequence_license": "CC0-1.0 (PDB archive)",
                    "license_source": "https://www.rcsb.org/pages/usage-policy",
                    "family_source": "Pfam via RCSB; annotations used for grouping",
                }
                selected.append(record)
                sequences.add(sequence)
                family_ids.update(families)
                counts[kind] += 1
                print(
                    f"selected {identifier}: {kind}, {len(sequence)} residues ({len(selected)}/60)",
                    flush=True,
                )
            except (KeyError, ValueError) as error:
                exclusions.append({"candidate": identifier, "reason": str(error)})
            atomic_json(
                root / "selection-progress.json", {"records": selected, "exclusions": exclusions}
            )
        if counts != {"monomer": protein_quota, "protein_ligand": ligand_quota}:
            raise ValueError(
                f"candidate pool exhausted for {lower}-{upper}: {counts}; retain evidence"
            )
    atomic_json(
        catalog_path,
        {
            "schema_version": "1.0",
            "seed": 42,
            "records": selected,
            "public_sequences_only": True,
            "exclusions": exclusions,
            "options": OPTIONS,
            "limitations": [
                "Convenience sample from first 500 sorted PDB entities per length band.",
                "Ligands are co-deposited components, not validated pharmacological pairs.",
                "Single-chain execution workload, not reconstruction of biological assemblies.",
            ],
        },
    )


def group_and_split(records):
    from Bio.Align import PairwiseAligner, substitution_matrices

    aligner = PairwiseAligner(
        mode="global",
        substitution_matrix=substitution_matrices.load("BLOSUM62"),
        open_gap_score=-10,
        extend_gap_score=-0.5,
    )
    parent = list(range(len(records)))

    def find(i):
        while parent[i] != i:
            i = parent[i]
        return i

    for i, left in enumerate(records):
        for j, right in enumerate(records[:i]):
            a, b = left["sequence"], right["sequence"]
            related = bool(set(left["families"]) & set(right["families"]))
            if not related and min(len(a), len(b)) / max(len(a), len(b)) >= 0.8:
                alignment = aligner.align(a, b)[0]
                counts = alignment.counts()
                coverage = (counts.identities + counts.mismatches) / max(len(a), len(b))
                related = counts.identities / alignment.length >= 0.3 and coverage >= 0.8
            if related:
                parent[find(i)] = find(j)
    groups = {}
    for i, record in enumerate(records):
        groups.setdefault(find(i), []).append(record)
    ordered = sorted(groups.values(), key=lambda g: min(r["job_id"] for r in g))
    random.Random(42).shuffle(ordered)
    if len(ordered) < 30:
        raise ValueError("too few distinct biological groups for the initial split")
    ntrain, ncal = round(0.6 * len(ordered)), round(0.2 * len(ordered))
    for index, group in enumerate(ordered):
        name = "group-" + min(r["job_id"] for r in group)
        split = "train" if index < ntrain else "calibration" if index < ntrain + ncal else "test"
        for record in group:
            record.update(biological_group_id=name, split=split)
    return records


def prepare(root):
    catalog = json.loads((root / "catalog.json").read_text())
    if (root / "frozen.json").exists():
        raise ValueError("benchmark already frozen")
    if (root / "prepared.json").exists():
        raise ValueError("already prepared; preserve the existing grouping")
    records = group_and_split(catalog["records"])
    (root / "inputs").mkdir(exist_ok=True)
    (root / "msas").mkdir(exist_ok=True)
    for record in records:
        sequence = record["sequence"]
        key = hashlib.sha256(sequence.encode()).hexdigest()
        record["msa"] = f"msas/{key}.a3m"
        record["input"] = f"inputs/{record['job_id']}.yaml"
        molecules = [{"protein": {"id": "A", "sequence": sequence, "msa": f"../{record['msa']}"}}]
        if record["ligand"]:
            molecules.append({"ligand": {"id": "B", "smiles": record["ligand"]["smiles"]}})
        (root / record["input"]).write_text(
            yaml.safe_dump({"version": 1, "sequences": molecules}, sort_keys=False)
        )
    atomic_json(
        root / "prepared.json",
        {
            **catalog,
            "records": records,
            "grouping": "Connected components: shared Pfam OR BLOSUM62 global alignment (gap open 10, extension 0.5), identity >=30% of alignment columns, paired-residue coverage >=80% of longer sequence, length ratio >=0.8. Remote homology may remain.",
        },
    )


def alignment_blocks(archive):
    """Parse ColabFold query blocks delimited by NUL; no remote path extraction."""
    blocks = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as handle:
        for member in handle.getmembers():
            if Path(member.name).name not in {"uniref.a3m", "bfd.mgnify30.metaeuk30.smag30.a3m"}:
                continue
            if not member.isfile() or member.size > 500_000_000:
                raise ValueError("unexpected MSA archive member")
            text = handle.extractfile(member).read().decode()
            for block in text.split("\x00"):
                block = block.strip()
                if not block:
                    continue
                header = block.splitlines()[0]
                if not re.fullmatch(r">[0-9]+", header):
                    raise ValueError("MSA archive has an unknown query header")
                blocks.setdefault(header[1:], []).append(block)
    if not blocks:
        raise ValueError("MSA archive has no recognized alignment members")
    return {key: "\n".join(values) + "\n" for key, values in blocks.items()}


def msa(root, limit):
    from scheduling.live import lease

    fd = lease(root / "msa.lock")
    if fd is None:
        raise RuntimeError("another alignment preparation process is active")
    try:
        return prepare_msas(root, limit)
    finally:
        os.close(fd)


def prepare_msas(root, limit):
    """Resume existing tickets first, then submit one serial batch of missing sequences."""
    catalog = json.loads((root / "prepared.json").read_text())
    if not catalog.get("public_sequences_only"):
        raise ValueError("external MSA preparation requires a public-source catalog")
    if (root / "frozen.json").exists():
        validate(root)
        return
    pending, batches = [], []
    for record in catalog["records"]:
        target = root / record["msa"]
        if target.exists():
            validate_a3m(target.read_text(), record["sequence"])
            continue
        ticket_path = target.with_suffix(".ticket.json")
        if ticket_path.exists():
            ticket = json.loads(ticket_path.read_text())
            if not ticket.get("id"):
                raise ValueError(
                    f"inspect unresolved MSA submission before retrying: {ticket_path}"
                )
            batches.append((ticket_path, ticket, [record]))
        else:
            pending.append(record)
    # A batch ticket is durable before POST; new invocations resume it first.
    for batch_path in sorted(root.glob("msa-batch*.ticket.json")):
        ticket = json.loads(batch_path.read_text())
        if not ticket.get("id"):
            raise ValueError("inspect ambiguous batch submission before retrying")
        by_id = {r["job_id"]: r for r in catalog["records"]}
        members = [by_id[key] for key in ticket["job_ids"]]
        if any(not (root / r["msa"]).exists() for r in members):
            batches.append((batch_path, ticket, members))
        pending = [r for r in pending if r["job_id"] not in ticket["job_ids"]]
    new_records = pending[:limit]
    if new_records:
        batch_path = root / (
            "msa-batch-"
            + hashlib.sha256("\n".join(r["job_id"] for r in new_records).encode()).hexdigest()[:16]
            + ".ticket.json"
        )
        batches.append((batch_path, None, new_records))
    for ticket_path, ticket, records in batches:
        if ticket is None:
            atomic_json(
                ticket_path,
                {
                    "status": "SUBMITTING",
                    "job_ids": [r["job_id"] for r in records],
                    "server": MSA_SERVER,
                    "time": time.time(),
                },
            )
            ticket = json.loads(
                request(
                    f"{MSA_SERVER}/ticket/msa",
                    {
                        "q": "".join(
                            f">{101 + i}\n{r['sequence']}\n" for i, r in enumerate(records)
                        ),
                        "mode": "env",
                    },
                )
            )
            ticket.update(
                job_ids=[r["job_id"] for r in records], server=MSA_SERVER, time=time.time()
            )
            atomic_json(ticket_path, ticket)
            if not ticket.get("id"):
                raise ValueError(
                    f"MSA service declined request: {ticket.get('status')}; stop, do not resubmit"
                )
        deadline = time.monotonic() + 1800
        while True:
            state = json.loads(request(f"{MSA_SERVER}/ticket/{ticket['id']}"))
            if state["status"] == "COMPLETE":
                break
            if state["status"] not in {"RUNNING", "PENDING", "UNKNOWN"}:
                raise ValueError(f"MSA service status {state['status']}; ticket preserved")
            if time.monotonic() >= deadline:
                raise TimeoutError("MSA polling deadline reached; resume same ticket later")
            time.sleep(10)
        archive_path = ticket_path.with_suffix(".tar.gz")
        if not archive_path.exists():
            download_archive(f"{MSA_SERVER}/result/download/{ticket['id']}", archive_path)
        blocks = alignment_blocks(archive_path.read_bytes())
        for i, record in enumerate(records):
            target = root / record["msa"]
            text = blocks[str(101 + i)]
            depth = validate_a3m(text, record["sequence"])
            target.write_text(text)
            atomic_json(
                target.with_suffix(".provenance.json"),
                {
                    "server": MSA_SERVER,
                    "ticket": ticket["id"],
                    "mode": "env",
                    "depth": depth,
                    "retrieved_at": datetime.now(UTC).isoformat(),
                    "sha256": digest(target),
                    "database_version": "not reported by API; frozen alignment bytes are authoritative",
                    "redistribution": "not bundled for release until constituent database terms reviewed",
                    "archive_sha256": digest(archive_path),
                    "query_id": 101 + i,
                },
            )
            print(f"MSA ready: {record['job_id']} ({depth} rows)", flush=True)
        time.sleep(2)


def freeze(root):
    if (root / "frozen.json").exists():
        raise ValueError("already frozen; use validate")
    catalog = json.loads((root / "prepared.json").read_text())
    if len(catalog["records"]) != 60:
        raise ValueError("the v1 public benchmark requires 60 targets")
    hashes = {
        "prepared.json": digest(root / "prepared.json"),
        "catalog.json": digest(root / "catalog.json"),
    }
    for record in catalog["records"]:
        validate_a3m((root / record["msa"]).read_text(), record["sequence"])
        for key in ("input", "msa"):
            hashes[record[key]] = digest(root / record[key])
        provenance = (root / record["msa"]).with_suffix(".provenance.json")
        hashes[str(provenance.relative_to(root))] = digest(provenance)
    for path in sorted((root / "source-cache").glob("*.json")):
        hashes[str(path.relative_to(root))] = digest(path)
    atomic_json(
        root / "frozen.json",
        {
            "schema_version": "1.0",
            "sha256": hashes,
            "records": len(catalog["records"]),
            "options": OPTIONS,
        },
    )


def validate(root):
    frozen = json.loads((root / "frozen.json").read_text())
    omitted = {}
    if (root / "public-release.json").exists():
        from experiments.public_bundle import validate_public_inventory

        omitted = validate_public_inventory(root)
    for relative, expected in frozen["sha256"].items():
        if relative in omitted:
            continue  # Explicit public projection: only non-execution source metadata is absent.
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()) or digest(path) != expected:
            raise ValueError(f"benchmark asset changed: {relative}")
    catalog = json.loads((root / "prepared.json").read_text())
    partitions = {}
    for record in catalog["records"]:
        group, split = record["biological_group_id"], record["split"]
        if split not in {"train", "calibration", "test"}:
            raise ValueError("invalid benchmark partition")
        if partitions.setdefault(group, split) != split:
            raise ValueError("biological group crosses benchmark partitions")
        for key in ("input", "msa"):
            if record[key] not in frozen["sha256"]:
                raise ValueError("benchmark record missing from hash inventory")
        validate_a3m((root / record["msa"]).read_text(), record["sequence"])
    return frozen


def snapshot(root, output):
    """Small public metadata record, excluding alignment and checkpoint bytes."""
    validate(root)
    if output.exists():
        raise ValueError("snapshot exists; preserve the published benchmark record")
    atomic_json(
        output,
        {
            "schema_version": "1.0",
            "prepared": json.loads((root / "prepared.json").read_text()),
            "frozen": json.loads((root / "frozen.json").read_text()),
            "frozen_sha256": digest(root / "frozen.json"),
        },
    )


def revise_ligands(root, output, codes, cache):
    """Fork a frozen corpus without replacing targets, groups, MSAs or evidence."""
    if (root / "public-release.json").exists():
        raise ValueError("ligand revision requires the complete original workload, not a public projection")
    from scheduling.features import cached_ccd_heavy_atoms

    frozen = validate(root)
    if output.exists():
        raise ValueError("revision output already exists; preserve prior benchmark versions")
    if output.resolve().is_relative_to(root.resolve()):
        raise ValueError("revision must be outside the source benchmark")
    prepared = json.loads((root / "prepared.json").read_text())
    requested = set(codes)
    available = {r["ligand"]["ccd"] for r in prepared["records"] if r.get("ligand")}
    if not requested or not requested <= available:
        raise ValueError("request CCD codes represented in the source catalog")
    components = {
        code: {
            "heavy_atoms": cached_ccd_heavy_atoms(code, cache),
            "cache_sha256": digest(cache / "mols" / f"{code}.pkl"),
        }
        for code in sorted(requested)
    }
    changes = []
    documents = {}
    for record in prepared["records"]:
        ligand = record.get("ligand")
        if not ligand or ligand["ccd"] not in requested:
            continue
        code = ligand["ccd"]
        if components[code]["heavy_atoms"] != ligand["heavy_atoms"]:
            raise ValueError(f"source and cached CCD heavy-atom counts differ for {code}")
        document = yaml.safe_load((root / record["input"]).read_text())
        entries = [entry["ligand"] for entry in document["sequences"] if "ligand" in entry]
        if len(entries) != 1 or entries[0].get("smiles") != ligand["smiles"]:
            raise ValueError("revision expects the original single-ligand SMILES input")
        entries[0].pop("smiles")
        entries[0]["ccd"] = code
        ligand["representation"] = "ccd"
        documents[record["input"]] = yaml.safe_dump(document, sort_keys=False)
        changes.append({"job_id": record["job_id"], "input": record["input"], "ccd": code,
                        "previous_sha256": frozen["sha256"][record["input"]]})
    output.mkdir(parents=True)
    for relative in frozen["sha256"]:
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, target)
    for relative, text in documents.items():
        (output / relative).write_text(text)
    for change in changes:
        change["revised_sha256"] = digest(output / change["input"])
    prepared["revision"] = {
        "source_benchmark_sha256": digest(root / "frozen.json"),
        "source_name": root.name,
        "reason": "Use cached CCD for selected conformer-generation failures; retain all targets, partitions and MSA bytes.",
        "components": components,
        "changes": changes,
    }
    atomic_json(output / "prepared.json", prepared)
    freeze(output)
    validate(output)
    validate(root)
    print(f"Created {output}: {len(changes)} ligand representations revised; all targets retained")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("fetch", "prepare", "msa", "freeze", "validate", "snapshot", "revise-ligands")
    )
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--ccd", action="append", default=[], help="CCD component to use in a new revision")
    parser.add_argument("--cache", type=Path, default=Path(os.environ.get("BOLTZ_CACHE", "/workspace/cache")))
    parser.add_argument(
        "--limit", type=int, default=6, help="maximum new public sequences in a serial MSA batch"
    )
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("limit must be positive")
    if args.command == "revise-ligands":
        if args.output is None or not args.ccd:
            parser.error("revise-ligands requires --output and at least one --ccd")
        revise_ligands(args.root.resolve(), args.output.resolve(), args.ccd, args.cache.resolve())
    elif args.command == "msa":
        msa(args.root.resolve(), args.limit)
    elif args.command == "snapshot":
        if args.output is None:
            parser.error("snapshot requires --output")
        snapshot(args.root.resolve(), args.output.resolve())
    else:
        globals()[args.command](args.root.resolve())


if __name__ == "__main__":
    main()
