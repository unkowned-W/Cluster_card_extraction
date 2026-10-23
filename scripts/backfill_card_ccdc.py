"""Match missing card CCDC identifiers against data/cluster_complex.csv.

Dry-run by default. --apply writes unambiguous DOI + metal-element/count
matches. Conflicting cards, structures or pre-existing identifiers stay pending.
Each changed card is backed up and every missing compound is audited.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ELEMENTS = set("H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr".split())
TOKEN = re.compile(r"([A-Z][a-z]?)(\d*(?:\.\d+)?)")
METALS = set("Li Be Na Mg Al K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Fr Ra Ac Th Pa U Np Pu".split())
SOLVENTS = {"H2 O1", "C1 H4 O1", "C2 H6 O1", "C2 H6 O1 S1", "C3 H7 N1 O1", "C3 H6 O1", "C4 H8 O1", "C4 H10 O1", "C5 H5 N1", "C6 H6", "C6 H14", "C7 H8", "C1 H2 Cl2", "C1 H1 Cl3", "C2 H3 N1"}


def doi_key(value: str) -> str:
    value = str(value or "").strip().lower()
    return re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value)


def empirical(text: str) -> Counter | None:
    """Accept only a *whole*, literal elemental formula; reject ligand aliases."""
    text = re.sub(r"\s+", "", str(text or ""))
    if not text:
        return None
    result = Counter()
    pos = 0
    for match in TOKEN.finditer(text):
        if match.start() != pos or match.group(1) not in ELEMENTS:
            return None
        result[match.group(1)] += Decimal(match.group(2) or "1")
        pos = match.end()
    return result if pos == len(text) and result else None


def csv_counts(text: str):
    parts = []
    for raw in text.split(","):
        raw = raw.strip()
        # CSD: "3(C4 H8 O1)" and "C100 H100 Dy4 1+,N1 O3 1-".
        m = re.fullmatch(r"(?:(\d+(?:\.\d+)?)\()?(.+?)(?:\))?(?:\s+\d+[+-])?", raw)
        if not m:
            return None
        if m.group(1) and not raw.endswith(")"):
            return None
        counts = empirical(m.group(2))
        if counts is None:
            return None
        multiplier = Decimal(m.group(1) or "1")
        parts.append((raw, Counter({k: v * multiplier for k, v in counts.items()})))
    return parts or None


def signature(counts):
    return tuple(sorted((k, v) for k, v in counts.items() if v))


def is_solvent_component(raw):
    bare = re.sub(r"^\d+(?:\.\d+)?\((.*?)\)$", r"\1", raw)
    return bare in SOLVENTS


def match_kind(card, csv_formula):
    counts = empirical(card)
    parts = csv_counts(csv_formula)
    if counts is None or parts is None:
        return ""
    total = sum((v for _, v in parts), Counter())
    if signature(counts) == signature(total):
        return "exact_total"
    retained = [v for raw, v in parts if not is_solvent_component(raw)]
    if len(retained) < len(parts) and retained and signature(counts) == signature(sum(retained, Counter())):
        return "exact_desolvated"
    return ""


def metal_signature(compound):
    """Explicit metals in card formula, never element-only metadata fallback.

    The material_class nuclearity is used only as a consistency guard when
    present; it does not supply a guessed metal count.
    """
    text = str(compound.get("formula") or "")
    # Some cards give both a coordination formula and an empirical formula.
    # Never sum the same atoms from both descriptions.
    if ";" in text:
        alternatives = [segment.strip() for segment in text.split(";")]
        empirical_parts = [segment for segment in alternatives if empirical(segment)]
        if len(empirical_parts) == 1:
            text = empirical_parts[0]
        else:
            return None
    counts = empirical(text)
    if counts is None:
        # Reject generic metal placeholders rather than infer their identity.
        if re.search(r"(?<![a-zA-Z])(?:Ln|RE|M)(?![a-z])", text):
            return None
        tokens = TOKEN.findall(text)
        if not tokens:
            return None
        counts = Counter()
        for element, number in tokens:
            if element in METALS:
                counts[element] += Decimal(number or "1")
    metals = {k: v for k, v in counts.items() if k in METALS and v}
    if not metals:
        return None
    # Other extracted metadata (including nuclearity) may itself be wrong.
    # This user-approved pass matches only the formula's literal metal part.
    return metals


def compatible_rows(compound, rows):
    expected = metal_signature(compound)
    if not expected:
        return []
    compatible = []
    for row in rows:
        parts = csv_counts(row["formula"])
        if not parts:
            continue
        actual = {k: v for k, v in sum((v for _, v in parts), Counter()).items() if k in METALS}
        if set(actual) == set(expected) and actual:
            ratios = {actual[k] / expected[k] for k in actual}
            if len(ratios) == 1:
                compatible.append(row)
    return compatible


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Back up and write safe matches")
    parser.add_argument("--cards", type=Path, default=ROOT / "data/extracted_cards")
    parser.add_argument("--catalog", type=Path, default=ROOT / "data/cluster_complex.csv")
    parser.add_argument("--report", type=Path, default=ROOT / "data/card_ccdc_match_review.csv")
    args = parser.parse_args()
    candidates = defaultdict(list)
    with args.catalog.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row["ccdc_number"].strip() and row["refcode"].strip():
                candidates[doi_key(row["doi"])].append(row)
    cards, missing, occupied = {}, [], defaultdict(set)
    for path in sorted(args.cards.glob("*.json")):
        obj = json.loads(path.read_text(encoding="utf-8"))
        cards[path] = obj
        doi = doi_key(obj.get("doi"))
        for i, compound in enumerate(obj.get("list_of_rare_earth_compounds", [])):
            if not compound.get("ccdc_numbers"):
                missing.append((path, obj, doi, i, compound))
            else:
                occupied[doi].update(map(str, compound["ccdc_numbers"]))
            occupied[doi].update(map(str, compound.get("ccdc_refcodes") or []))

    # A structure must not be assigned to two currently missing cards.
    competitors = defaultdict(set)
    for path, obj, doi, i, compound in missing:
        for row in compatible_rows(compound, candidates[doi]):
            competitors[(doi, row["ccdc_number"], row["refcode"])].add((path, i))

    audit, updates = [], []
    for path, obj, doi, i, compound in missing:
        rows = candidates[doi]
        metal_candidates = compatible_rows(compound, rows)
        matches = [(row, match_kind(compound.get("formula"), row["formula"])) for row in rows]
        matches = [(row, kind) for row, kind in matches if kind]
        distinct = {(row["ccdc_number"], row["refcode"]) for row, _ in matches}
        distinct_metal = {(row["ccdc_number"], row["refcode"]) for row in metal_candidates}
        if not rows:
            status = "doi_not_in_catalog"
        elif metal_signature(compound) is None:
            status = "card_metal_formula_not_determinable"
        elif not metal_candidates:
            status = "no_metal_formula_match"
        elif len(distinct_metal) > 1:
            status = "multiple_metal_matching_structures"
        else:
            row = metal_candidates[0]
            key = (doi, row["ccdc_number"], row["refcode"])
            if len(competitors[key]) > 1:
                status = "multiple_competing_cards"
            elif row["ccdc_number"] in occupied[doi] or row["refcode"] in occupied[doi]:
                status = "identifier_already_used_in_doi"
            elif compound.get("ccdc_refcodes"):
                status = "existing_refcode_needs_review"
            else:
                kind = match_kind(compound.get("formula"), row["formula"]) or "metal_stoichiometry_ratio"
                status = "safe_" + kind
                updates.append((path, i, row, kind))
        audit.append({
            "card_file": path.name, "compound_index_1based": i + 1, "doi": obj.get("doi", ""),
            "compound_label": compound.get("compound_label") or "", "card_formula": compound.get("formula") or "",
            "status": status, "catalog_doi_rows": len(rows),
            "metal_compatible_count": len(metal_candidates),
            "metal_compatible_candidates": " | ".join(f'{r["ccdc_number"]}/{r["refcode"]}: {r["formula"]}' for r in metal_candidates),
            "exact_match_ccdc_refcode_formula": " | ".join(f'{r["ccdc_number"]}/{r["refcode"]}: {r["formula"]} ({kind})' for r, kind in matches),
            "doi_candidates_ccdc_refcode_formula": " | ".join(f'{r["ccdc_number"]}/{r["refcode"]}: {r["formula"]}' for r in rows),
        })

    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(audit[0]))
        writer.writeheader()
        writer.writerows(audit)
    if args.apply and updates:
        backup = args.cards.parent / ("card_ccdc_backup_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
        backup.mkdir(parents=True, exist_ok=False)
        for path in {path for path, _, _, _ in updates}:
            shutil.copy2(path, backup / path.name)
        for path, i, row, kind in updates:
            compound = cards[path]["list_of_rare_earth_compounds"][i]
            compound["ccdc_numbers"] = [row["ccdc_number"]]
            compound["ccdc_refcodes"] = [row["refcode"]]
            compound.setdefault("source_locations", []).append({
                "field": "ccdc_numbers; ccdc_refcodes", "source": "external_metadata",
                "location": f'data/cluster_complex.csv; DOI + formula ({kind})',
            })
        for path in {path for path, _, _, _ in updates}:
            path.write_text(json.dumps(cards[path], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("backup:", backup)
    print("report:", args.report)
    print("missing:", len(missing), "safe matches:", len(updates), "applied:", len(updates) if args.apply else 0)
    print("statuses:", dict(Counter(r["status"] for r in audit)))


if __name__ == "__main__":
    main()
