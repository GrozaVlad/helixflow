# HelixFlow public workload data notice

Review date: 16 November 2026. This notice concerns the public input bundle,
not the entire original source cache, model weights, or the software license.
It records a source-policy review, not legal certification or an upstream endorsement.

## Release decision and scope

The public bundle retains the original 60 Boltz inputs, 60 A3M alignments,
60 alignment-provenance records, catalog and prepared metadata. The 322 cached
RCSB responses are excluded because they contain integrated annotations from
multiple providers, including DrugBank, whose unrestricted redistribution was
not established. RCSB explicitly distinguishes integrated external data from
PDB archive data in its [usage policy](https://www.rcsb.org/pages/policies).

The original `frozen.json` and all retained scientific files are unchanged.
`public-release.json` identifies omissions by original path and hash. Metadata
omission does not change the sequences, ligands, MSAs, split assignments, or
experimental results. Original provenance files retain their historical
pending-review notices; this dated release notice supplies the later decision.

## Data sources and attribution

| Material | Attribution and license basis |
| --- | --- |
| PDB-derived target sequences and chemical component data | Worldwide Protein Data Bank and RCSB PDB; CC0 1.0 for PDB archive data. Preserve PDB identifiers, original structure publication DOIs, and source URLs in `catalog.json` and `prepared.json`. [RCSB policy](https://www.rcsb.org/pages/policies); [CC0](https://creativecommons.org/publicdomain/zero/1.0/). |
| Pfam family assignments used for grouping | Pfam contributors at EMBL-EBI; CC0. Cached assignments identify Pfam 34.0, but only prepared family identifiers/grouping metadata are included here. [Pfam documentation](https://interpro-documentation.readthedocs.io/en/latest/pfam.html). |
| UniProt/UniRef-derived alignment sequences | The UniProt Consortium; CC BY 4.0 for copyrightable database content. [UniProt license](https://www.uniprot.org/help/license); [machine-readable policy](https://rest.uniprot.org/help/license); [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). |
| BFD-derived sequences | Martin Steinegger, Milot Mirdita, Johannes Söding and contributing data providers; CC BY 4.0 on the BFD distribution. [BFD database and license](https://bfd.mmseqs.com/). |
| ColabFold search databases and resulting alignment adaptations | Milot Mirdita, Konstantin Schütze, Yoshitaka Moriwaki, Lim Heo, Sergey Ovchinnikov, Martin Steinegger, and underlying database contributors. The [distribution page](https://colabfold.mmseqs.com/) states CC BY 4.0; the [ColabFold paper](https://doi.org/10.1038/s41592-022-01488-1) states CC BY-SA 4.0. The alignment adaptations in this bundle follow CC BY-SA 4.0 conservatively; underlying source rights and attribution are preserved. |

ColabFoldDB incorporates BFD/MGnify, MetaEuk, SMAG, TOPAZ, MGV, GPD and MetaClust2,
as described on its distribution page. This bundle uses ColabFold's published
database redistribution terms; it is not a new independent license grant over
every upstream contribution. Preserve this notice and the upstream references.

## Alignment conditions and modifications

For the ColabFold-derived alignment adaptations, apply
[Creative Commons Attribution-ShareAlike 4.0 International](https://creativecommons.org/licenses/by-sa/4.0/)
([legal code](https://creativecommons.org/licenses/by-sa/4.0/legalcode.en)).
Give credit, link to the license, identify changes, retain supplied notices, and
distribute adaptations under the same or a compatible license. Do not impose
additional legal or technological restrictions. This does not relicense public
domain elements, remove underlying CC BY permissions, or change the Apache-2.0
license of HelixFlow's separate software.

The preparation code selected query-specific results from ColabFold's
`uniref.a3m` and `bfd.mgnify30.metaeuk30.smag30.a3m` result members, joined matching
query blocks, and wrote per-input A3M files. These are aligned subsets/derived
results, not complete upstream databases. No alignment bytes were changed during
public packaging. Two heme ligand inputs were revised to `ccd: HEM` before the
original experiment; public packaging makes no further input modifications.

The results were retrieved from `https://api.colabfold.com` on 21 October 2026
using `env` mode. Exact database versions were not reported by the API. The
[server database history](https://github.com/sokrypton/ColabFold/wiki/MSA-Server-Database-History)
provides context, not verified per-job versions. Original retrieval times and
alignment hashes remain in individual provenance records.

## Recommended scientific citations

- Mirdita M. et al. ColabFold: making protein folding accessible to all.
  Nature Methods 19, 679–682 (2022). <https://doi.org/10.1038/s41592-022-01488-1>.
- Steinegger M., Mirdita M. and Söding J. Protein-level assembly increases
  protein sequence recovery from metagenomic samples manyfold. Nature Methods
  (2019). <https://doi.org/10.1038/s41592-019-0437-4>.
- Steinegger M. and Söding J. Clustering huge protein sequence sets in linear
  time. Nature Communications (2018). <https://doi.org/10.1038/s41467-018-04964-5>.
- RCSB PDB and the original structure authors identified in the catalog;
  the UniProt Consortium and Pfam resource publications relevant to their use.

These resources are supplied without warranties. The licenses do not establish
biological accuracy, clinical suitability, or clearance of patents and other
rights outside their scope. No endorsement by an upstream provider is implied.
