"""Build a traceable card subset for large clusters and review knowledge."""

import csv
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DEST = DATA / "high_quality_samples"


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def copy_card(source):
    source = Path(source)
    if not source.is_absolute():
        source = ROOT / source
    if not source.is_file():
        return "", "missing_source"
    target = DEST / source.parent.name / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target.relative_to(ROOT).as_posix(), "copied"


def main():
    ledger = []
    structures = {}
    for path in sorted((DATA / "cif_structure_cards").glob("*.json")):
        try:
            structures[path] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

    for paper in read_csv(DATA / "process_csv" / "large_cluster_papers_gt20.csv"):
        doi = paper["doi"].strip()
        source_rel = paper.get("card_path") or f"data/extracted_cards/{doi.replace('/', '_')}.json"
        source = ROOT / source_rel
        target, status = copy_card(source)
        card = {}
        if status == "copied":
            try:
                card = json.loads(source.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                status = "invalid_json"
        qualifying = []
        for compound in card.get("list_of_rare_earth_compounds", []) or []:
            nuclearity = (compound.get("material_class") or {}).get("nuclearity")
            if isinstance(nuclearity, int) and not isinstance(nuclearity, bool) and nuclearity > 20:
                qualifying.append(compound)
        ledger.append({"record_type": "synthesis_card", "source_doi": doi,
                       "review_doi": "", "card_id": "", "compound_label": "",
                       "nuclearity": "", "ccdc_number": "", "refcode": "",
                       "source_path": source_rel, "sample_path": target,
                       "match_basis": "large_cluster_papers_gt20.csv DOI/card_path",
                       "status": status, "notes": f"qualifying_compounds={len(qualifying)}"})

        for compound in qualifying:
            label = compound.get("compound_label") or compound.get("compound_name") or ""
            nuclearity = (compound.get("material_class") or {}).get("nuclearity", "")
            ccdc = [str(v) for v in compound.get("ccdc_numbers") or []]
            refcodes = [str(v) for v in compound.get("ccdc_refcodes") or []]
            ccdc_keys = {v.casefold() for v in ccdc}
            refcode_keys = {v.casefold() for v in refcodes}
            hits = set()
            for path, structure in structures.items():
                if (str(structure.get("ccdc_number", "")).casefold() in ccdc_keys
                        or str(structure.get("refcode", "")).casefold() in refcode_keys):
                    hits.add(path)
            if not hits:
                ledger.append({"record_type": "structure_card", "source_doi": doi,
                               "review_doi": "", "card_id": "", "compound_label": label,
                               "nuclearity": nuclearity, "ccdc_number": "|".join(ccdc),
                               "refcode": "|".join(refcodes), "source_path": "", "sample_path": "",
                               "match_basis": "exact CCDC/refcode lookup",
                               "status": "no_matching_structure_card",
                               "notes": "No CIF structure card matched this >20-metal compound."})
            for path in sorted(hits):
                structure = structures[path]
                target, status = copy_card(path)
                ledger.append({"record_type": "structure_card", "source_doi": doi,
                               "review_doi": "", "card_id": "", "compound_label": label,
                               "nuclearity": nuclearity, "ccdc_number": structure.get("ccdc_number", ""),
                               "refcode": structure.get("refcode", ""),
                               "source_path": path.relative_to(ROOT).as_posix(), "sample_path": target,
                               "match_basis": "exact CCDC/refcode from qualifying compound",
                               "status": status, "notes": ""})

    for review in read_csv(DATA / "process_csv" / "review_knowledge_index.csv"):
        source_rel = review.get("card_file", "")
        target, status = copy_card(ROOT / source_rel)
        ledger.append({"record_type": "review_card", "source_doi": "",
                       "review_doi": review.get("doi", ""), "card_id": review.get("card_id", ""),
                       "compound_label": "", "nuclearity": "", "ccdc_number": "", "refcode": "",
                       "source_path": source_rel, "sample_path": target,
                       "match_basis": "complete review_knowledge_index.csv set",
                       "status": status,
                       "notes": f"category={review.get('category', '')}; evidence={review.get('evidence_locations', '')}"})

    fields = ["record_type", "source_doi", "review_doi", "card_id", "compound_label",
              "nuclearity", "ccdc_number", "refcode", "source_path", "sample_path",
              "match_basis", "status", "notes"]
    DEST.mkdir(parents=True, exist_ok=True)
    with (DEST / "sample_ledger.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(ledger)
    counts = {kind: sum(row["record_type"] == kind and row["status"] == "copied" for row in ledger)
              for kind in ("synthesis_card", "structure_card", "review_card")}
    structure_files = len(list((DEST / "cif_structure_cards").glob("*.json")))
    (DEST / "README.md").write_text(
        "# High-quality card sample set\n\n"
        "Cards are copied; source files are unchanged. Rebuild from the project root with "
        "`python scripts/build_high_quality_samples.py`.\n\n"
        "- `extracted_cards/`: synthesis cards selected by the >20-metal paper list.\n"
        "- `cif_structure_cards/`: CIF cards matched by exact CCDC number or refcode to a qualifying compound.\n"
        "- `review_knowledge_cards/`: all currently indexed review knowledge cards, as a separate class.\n"
        "- `sample_ledger.csv`: provenance and match status, one row per card or unresolved expected structure.\n\n"
        f"Last build: {counts['synthesis_card']} synthesis cards, {structure_files} structure-card files, "
        f"{counts['review_card']} review cards; {len(ledger)} ledger rows. Review cards are not asserted to map "
        "one-to-one to the large-cluster papers.\n", encoding="utf-8")
    print(f"synthesis={counts['synthesis_card']}, structure_files={structure_files}, "
          f"review={counts['review_card']}, ledger_rows={len(ledger)}")


if __name__ == "__main__":
    main()
