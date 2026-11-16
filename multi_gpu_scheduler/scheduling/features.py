from __future__ import annotations

import os
import pickle
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from .models import JobFeatures

_SEQUENCE = re.compile(r"[^A-Za-z]")
_SMILES_ATOM = re.compile(r"\[[^\]]+\]|Br|Cl|Si|Se|[BCNOFPSIbcnops]")


def cached_ccd_heavy_atoms(code: str, cache: Path) -> int:
    """Read Boltz's trusted molecular cache, never a user-uploaded pickle.

    The Boltz environment supplies RDKit for its cached Mol objects. A missing
    component/dependency is an error, not a one-atom resource estimate.
    """
    if not isinstance(code, str) or not re.fullmatch(r"[A-Z0-9]{1,10}", code):
        raise ValueError(f"invalid CCD component code: {code!r}")
    path = cache / "mols" / f"{code}.pkl"
    if not path.is_file():
        raise ValueError(f"CCD component {code} missing from trusted Boltz cache: {path}")
    try:
        with path.open("rb") as handle:
            molecule = pickle.load(handle)  # Same trusted assets used by Boltz itself.
        count = molecule.GetNumHeavyAtoms()
    except (ImportError, AttributeError) as error:
        raise ValueError("CCD features require the Boltz/RDKit environment and molecular cache") from error
    if type(count) is not int or count <= 0:
        raise ValueError(f"invalid heavy-atom count for CCD component {code}")
    return count


def _clean_sequence(value: str) -> str:
    return _SEQUENCE.sub("", value).upper()


def _chain_count(identifier: Any) -> int:
    if isinstance(identifier, list):
        return max(1, len(identifier))
    return 1


def _a3m_depth(path: Path) -> int:
    if not path.is_file():
        return 0
    return sum(line.startswith(">") for line in path.read_text(encoding="utf-8").splitlines())


def _options(values: dict[str, Any] | None) -> tuple[int, int, int]:
    values = values or {}
    return (
        int(values.get("recycling_steps", 3)),
        int(values.get("sampling_steps", 200)),
        int(values.get("diffusion_samples", 1)),
    )


def _fasta_features(path: Path, options: dict[str, Any] | None) -> JobFeatures:
    sequences: list[str] = []
    current: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if current:
                sequences.append(_clean_sequence("".join(current)))
                current = []
        else:
            current.append(line)
    if current:
        sequences.append(_clean_sequence("".join(current)))
    if not sequences or any(not sequence for sequence in sequences):
        raise ValueError(f"no valid FASTA sequences in {path}")
    recycling, sampling, diffusion = _options(options)
    total = sum(map(len, sequences))
    return JobFeatures(
        job_type="monomer" if len(sequences) == 1 else "protein_complex",
        total_residues=total,
        max_chain_length=max(map(len, sequences)),
        protein_chains=len(sequences),
        estimated_tokens=total,
        input_bytes=path.stat().st_size,
        recycling_steps=recycling,
        sampling_steps=sampling,
        diffusion_samples=diffusion,
    )


def _yaml_features(
    path: Path,
    options: dict[str, Any] | None,
    msa_depth_override: int | None,
    cache: Path,
    ccd_atom_counts: Mapping[str, int] | None,
) -> JobFeatures:
    if ccd_atom_counts is not None and not isinstance(ccd_atom_counts, Mapping):
        raise ValueError("CCD atom counts must be a mapping")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("sequences"), list):
        raise ValueError(f"invalid Boltz YAML in {path}")  # noqa: TRY004

    protein_lengths: list[int] = []
    protein_chains = 0
    ligand_count = 0
    ligand_atoms = 0
    other_tokens = 0
    msa_depth = 0
    for entry in document["sequences"]:
        if not isinstance(entry, dict):
            continue
        if "protein" in entry:
            protein = entry["protein"] or {}
            sequence = _clean_sequence(str(protein.get("sequence", "")))
            copies = _chain_count(protein.get("id"))
            if sequence:
                protein_lengths.extend([len(sequence)] * copies)
                protein_chains += copies
            msa = protein.get("msa")
            if isinstance(msa, str) and msa not in {"empty", "none"}:
                msa_depth = max(msa_depth, _a3m_depth((path.parent / msa).resolve()))
        elif "ligand" in entry:
            ligand = entry["ligand"] or {}
            copies = _chain_count(ligand.get("id"))
            ligand_count += copies
            smiles = str(ligand.get("smiles", ""))
            ligand_atoms += len(_SMILES_ATOM.findall(smiles)) * copies
            if smiles and ligand.get("ccd"):
                raise ValueError("ligands require exactly one of smiles or ccd")
            if not smiles and ligand.get("ccd"):
                codes = ligand["ccd"]
                codes = [codes] if isinstance(codes, str) else codes
                if not isinstance(codes, list) or not codes:
                    raise ValueError("CCD ligand requires a code or nonempty list of codes")
                for code in codes:
                    if not isinstance(code, str) or not re.fullmatch(r"[A-Z0-9]{1,10}", code):
                        raise ValueError(f"invalid CCD component code: {code!r}")
                    count = (
                        ccd_atom_counts[code]
                        if ccd_atom_counts is not None and code in ccd_atom_counts
                        else cached_ccd_heavy_atoms(code, cache)
                    )
                    if type(count) is not int or count <= 0:
                        raise ValueError(f"invalid heavy-atom count for CCD component {code}")
                    ligand_atoms += count * copies
        elif "dna" in entry or "rna" in entry:
            molecule = entry.get("dna") or entry.get("rna") or {}
            other_tokens += len(_clean_sequence(str(molecule.get("sequence", "")))) * _chain_count(
                molecule.get("id")
            )

    if not protein_lengths:
        raise ValueError(f"Boltz scheduling corpus requires a protein sequence in {path}")
    if msa_depth_override is not None:
        msa_depth = msa_depth_override
    recycling, sampling, diffusion = _options(options or document.get("options"))
    total_residues = sum(protein_lengths)
    estimated_tokens = total_residues + ligand_atoms + other_tokens
    job_type = (
        "protein_ligand"
        if ligand_count
        else "protein_complex"
        if protein_chains > 1
        else "monomer"
    )
    return JobFeatures(
        job_type=job_type,
        total_residues=total_residues,
        max_chain_length=max(protein_lengths),
        protein_chains=protein_chains,
        ligand_count=ligand_count,
        ligand_atoms=ligand_atoms,
        msa_depth=msa_depth,
        estimated_tokens=estimated_tokens,
        input_bytes=path.stat().st_size,
        recycling_steps=recycling,
        sampling_steps=sampling,
        diffusion_samples=diffusion,
    )


def extract_features(
    path: Path,
    *,
    options: dict[str, Any] | None = None,
    msa_depth_override: int | None = None,
    cache: Path | None = None,
    ccd_atom_counts: Mapping[str, int] | None = None,
) -> JobFeatures:
    """Extract only submission-time features; no biological result is inspected."""

    suffix = path.suffix.lower()
    if suffix in {".fasta", ".fa"}:
        return _fasta_features(path, options)
    if suffix in {".yaml", ".yml"}:
        return _yaml_features(
            path, options, msa_depth_override,
            cache if cache is not None else Path(os.environ.get("BOLTZ_CACHE", "/workspace/cache")),
            ccd_atom_counts,
        )
    raise ValueError(f"unsupported Boltz input extension: {suffix}")
