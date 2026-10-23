# Extraction rules

## Unit of extraction

The article is the top-level record. Each distinct synthesized, structurally characterized, magnetically characterized, or optically characterized rare-earth compound is one card. Do not merge different compound numbers, lanthanide analogues, solvates, polymorphs, or CCDC depositions unless the paper clearly treats them as the same material.

## Completeness and empty-card guard

Before finalizing, create a mental inventory of every numbered/specified rare-earth structure in the article, including metal analogues, solvent-free/solvated phases, and distinct deposition records. Cross-check it against supplied CCDC metadata and the DOI-specific rows of `data/cluster_complex.csv`. If a metadata entry cannot be mapped confidently, investigate the original PDF or crystallographic information rather than guessing. The catalog is a completeness check, not scientific authority; report a genuine inconsistency for manual review. Never return a title describing the extraction process or an empty compound list merely because the extraction was interrupted.

## Identity resolution

Resolve compound labels across the full document before extracting details. Use title, schemes, captions, crystallographic tables, experimental sections, and supplied metadata together. Formula/name/CCDC matches require positive support. If a mapping remains ambiguous, leave the uncertain scalar null instead of guessing.

## Material category

- `cluster`: discrete polynuclear rare-earth or rare-earth/other-metal molecular core.
- `complex`: mononuclear complex or coordination compound that does not satisfy the cluster definition.
- `unknown`: insufficient information.

Record nuclearity when defensible. Use `dimensionality` and `structural_family` for coordination polymers and MOFs without automatically mislabeling them as clusters.

## Synthesis and SI ledger

Extract the actual preparation rather than a characterization paragraph. Preserve named reagents, every reported quantity with its unit, solvent, temperature, time, pH, method/vessel, work-up, crystallization, and yield when reported.

Do not create a fixed atmosphere field. If an atmosphere is explicitly important (nitrogen, argon, oxygen, air, Schlenk conditions), retain it naturally in `procedure`.

`main_text_has_explicit_synthesis=true` only when the main article contains an explicit reagent/starting-material name, at least one numerical amount/concentration/equivalent/mass/volume/mol value, and enough procedural context to identify preparation. `si_used=true` means a separately supplied SI document provided synthesis content.

The validator derives whether SI is still needed. That operational result is written to `data/process_csv/si_required.csv` and must not be stored in the scientific JSON card.

## Properties

Only retain magnetic and optical results.

Magnetic examples: susceptibility, chiMT, magnetization, coupling, SMM/SIM, relaxation, blocking temperature, coercivity, and magnetocaloric effect.

Optical examples: absorption, excitation/emission, luminescence, lifetime, quantum yield, CIE coordinates, up/down-conversion, and optical sensing.

Record `reported` first, then `property_type`, then numerical measurements and conditions. Put qualitative conclusions and any genuinely demonstrated magnetic/optical function in `summary`. Do not extract speculative applications mentioned only in the introduction or conclusion, and do not maintain a separate list of niche applications.

## Source locations

For a giant cluster with a figure or discussion that decomposes its architecture, an optional `structure_description` may briefly describe the shape, named building units, their linkage, and assembly hierarchy. Attribute it to the primary article (including figure and page) in `source_locations`; do not infer subunits from the formula or transfer a review's general motif to a particular compound. Identify proposed assembly routes as proposals, not observed intermediates. Leave the field absent when the source is inconclusive; do not change synthesis or property fields to accommodate it.

Keep source tracking lightweight:

- `field`: card field supported by the location;
- `source`: main text, SI, external metadata, or unknown;
- `location`: section/table/figure/page when available.

Do not copy long excerpts. An empty array is acceptable when the converted Markdown does not preserve reliable locations.
