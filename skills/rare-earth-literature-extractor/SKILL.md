---
name: rare-earth-literature-extractor
description: Extract verified rare-earth cluster and complex structure cards from MinerU Markdown or local PDFs, connect compounds to CCDC metadata, retain magnetic/optical properties, and maintain a separate SI-completion DOI ledger. Use for Codex CLI literature extraction; do not use for downloading papers.
---

# Rare-earth Literature Extractor

Extract one scientific JSON record per article. Prefer cached MinerU Markdown; use the original PDF only when Markdown is missing, damaged, or ambiguous.

## Workflow

1. Read [references/extraction-rules.md](references/extraction-rules.md) and [references/card-schema.md](references/card-schema.md).
2. Treat article Markdown/PDF as `main_text`; treat separately supplied supplements only as `supporting_information`.
3. Prefer the flat Markdown file `documents/md/<DOI-filename-stem>.md`. If a package directory exists, use `article.md` inside it. Consult the original PDF only for broken formulae, tables, schemes, images, or unresolved mappings.
4. Load all CCDC metadata rows for the DOI. Match refcodes, formulae, and CCDC numbers to the correct compounds; never assign every structure row to every compound. For each DOI, reconcile the original `data/cluster_complex.csv` CCDC/refcode/formula rows with paper-supported structures; do not silently omit rows. If a row cannot be assigned, investigate and flag it rather than inventing an assignment.
5. Read globally enough to resolve labels and anaphora before filling cards. Enumerate every structurally characterized rare-earth compound (including analogous metal substitutions and separately reported solvates/polymorphs); compare the full list against experimental sections, crystallographic tables, figures, and CCDC metadata before returning. A plausible single structure is not proof the paper has no others. An empty list is only valid if careful source review establishes no in-scope compounds and there is no contrary rare-earth metadata. Never submit a progress message or placeholder title as the article title.
6. Record properties in this order: reported or not; magnetic/optical/both; qualitative summary; then measured values and conditions. Ignore unrelated property families and speculative niche applications.
7. Apply the explicit synthesis rule. Do not emit `needs_si` or `si_reason` in JSON. The validator derives SI requirements and writes them to CSV.
8. Return only JSON conforming to [references/output_schema.json](references/output_schema.json).
9. Run `scripts/validate_and_save.py` to validate the card, save it, and update the SI ledger. The batch runner rejects empty cards with rare-earth metadata and rejects CCDC numbers from the DOI-specific original catalog when still unreferenced rather than marking such articles complete; revisit the source and any apparent DOI/CCDC mismatch instead of fabricating a structure.

## Explicit synthesis rule

`main_text_has_explicit_synthesis=true` only when the main article provides, for that compound or an unambiguous shared procedure:

- at least one explicit starting-material/reagent name;
- at least one numerical reagent amount, concentration, stoichiometric equivalent, mass, volume, or mole value;
- enough procedural context to identify preparation rather than characterization.

A reagent list without amounts, “prepared by the reported method,” a scheme without quantities, crystallization-only detail, or characterization data is insufficient. If supplied SI contains the missing procedure, keep `main_text_has_explicit_synthesis=false`, set `si_used=true`, and extract the SI procedure.

## Property invariants

- No requested property: `reported=false`, `property_type="none"`, measurements empty.
- Magnetic only: `property_type="magnetic"`.
- Optical only: `property_type="optical"`.
- Both genuinely reported: `property_type="both"`; tag every measurement with its type.
- Crystal color alone is not an optical measurement.
- Do not infer magnetism or luminescence from the elements.
- Preserve values, units, and reported conditions.
- No standalone applications array. A demonstrated magnetic/optical function may be mentioned briefly in `summary`.

## Card/workflow boundary

The JSON card contains scientific content. Download state, MinerU conversion state, extraction state, and SI-needed state belong in CSV ledgers. Atmosphere is not a fixed field; preserve it in `procedure` only when explicitly reported and relevant. `source_locations` stores concise locations without copied excerpts.

## Batch helpers

Notebook 6, 6.1, and 6.2 use a bounded structural-evidence excerpt from Markdown figure captions and adjacent structural paragraphs. The excerpt is a search aid, not a substitute for checking the article, compound identities, or SI. Full-card extraction still requires other article sections; this prefilter does not by itself guarantee lower total model token use.

From the project root:

```powershell
python scripts/mineru_pdf_parser.py --limit 5
python skills/rare-earth-literature-extractor/scripts/build_queue.py
python skills/rare-earth-literature-extractor/scripts/run_codex_batch.py --limit 5
```

Start with a small batch, inspect MinerU output and cards, then increase the limit.

## SI-only completion of an existing card

When the runner uses `--si-completion`, do **not** follow the full-article workflow above. Read the supplied existing card, the extracted previous-log diagnostics, the SI ledger reason, and only the listed SI files. Do not open article Markdown/PDF or re-extract compound identities or properties. Match each SI synthesis to its existing zero-based compound index using labels and formulas. Return only a `si_patch_schema.json` patch: newly supported missing synthesis facts and the SI section location; use an empty `updates` array if no matching preparation can be verified. Do not invent amounts or replace existing values. The runner merges only missing synthesis fields and validates the result; an incomplete compound remains on the SI ledger.
