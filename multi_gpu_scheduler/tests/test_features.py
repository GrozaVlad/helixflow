from pathlib import Path

import pytest

from scheduling.features import extract_features


def test_extracts_multimer_ligand_features(tmp_path: Path):
    input_path = tmp_path / "complex.yaml"
    input_path.write_text(
        """version: 1
sequences:
  - protein:
      id: [A, B]
      sequence: ACDE
  - ligand:
      id: L
      smiles: CC(=O)O
""",
        encoding="utf-8",
    )
    features = extract_features(input_path, msa_depth_override=25)
    assert features.job_type == "protein_ligand"
    assert features.protein_chains == 2
    assert features.total_residues == 8
    assert features.ligand_count == 1
    assert features.ligand_atoms == 4
    assert features.msa_depth == 25
    assert features.estimated_tokens == 12


def test_extracts_multiple_fasta_chains(tmp_path: Path):
    input_path = tmp_path / "complex.fasta"
    input_path.write_text(">A\nACDE\n>B\nFGH\n", encoding="utf-8")
    features = extract_features(input_path)
    assert features.job_type == "protein_complex"
    assert features.protein_chains == 2
    assert features.total_residues == 7
    assert features.max_chain_length == 4


def test_ccd_counts_heavy_atoms_copies_and_multiple_components(tmp_path):
    source = tmp_path / "heme.yaml"
    source.write_text("version: 1\nsequences:\n- protein: {id: A, sequence: AAA}\n"
                      "- ligand: {id: [B, C], ccd: [HEM, MG]}\n")
    features = extract_features(source, ccd_atom_counts={"HEM": 43, "MG": 1})
    assert features.ligand_atoms == 88
    assert features.estimated_tokens == 91
    assert features.ligand_count == 2


def test_ccd_reads_trusted_cache_and_never_guesses(tmp_path, monkeypatch):
    from scheduling import features as module

    source = tmp_path / "heme.yaml"
    source.write_text("version: 1\nsequences:\n- protein: {id: A, sequence: AAA}\n"
                      "- ligand: {id: B, ccd: HEM}\n")
    cache = tmp_path / "cache"
    with pytest.raises(ValueError, match="missing from trusted Boltz cache"):
        extract_features(source, cache=cache)
    (cache / "mols").mkdir(parents=True)
    (cache / "mols/HEM.pkl").write_bytes(b"test fixture only")

    class Molecule:
        def GetNumHeavyAtoms(self):
            return 43

    monkeypatch.setattr(module.pickle, "load", lambda handle: Molecule())
    features = extract_features(source, cache=cache)
    assert features.ligand_atoms == 43
    assert features.estimated_tokens == 46
    for count in (0, -1, True, 4.3):
        with pytest.raises(ValueError, match="invalid heavy-atom count"):
            extract_features(source, ccd_atom_counts={"HEM": count})
    with pytest.raises(ValueError, match="invalid CCD component code"):
        module.cached_ccd_heavy_atoms("../HEM", cache)
