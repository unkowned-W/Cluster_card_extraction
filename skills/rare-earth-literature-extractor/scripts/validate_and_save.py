#!/usr/bin/env python3
"""Validate one extracted card, derive SI status, save it, and update ledgers."""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
PROPERTY_TYPES = {"none", "magnetic", "optical", "both"}


def normalize_doi(value: str | None) -> str:
    doi = (value or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "http://dx.doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix):].strip()
    return doi.rstrip(". ,;")


def safe_stem(doi: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", doi, flags=re.ASCII).strip("._")


def require_keys(obj: dict[str, Any], keys: list[str], where: str) -> None:
    missing = [key for key in keys if key not in obj]
    if missing:
        raise ValueError(f"{where} missing keys: {', '.join(missing)}")


def has_numerical_amount(value: Any) -> bool:
    return isinstance(value, str) and bool(re.search(r"\d", value))


def validate_and_derive(
    data: dict[str, Any], expected_doi: str | None = None,
    expected_ccdc: list[str] | None = None, require_compounds: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    require_keys(data, ["title", "doi", "list_of_rare_earth_compounds"], "article")
    doi = normalize_doi(data.get("doi"))
    if not doi:
        raise ValueError("Article DOI is empty")
    if expected_doi and doi != normalize_doi(expected_doi):
        raise ValueError(f"DOI mismatch: expected {expected_doi}, got {doi}")
    data["doi"] = doi

    compounds = data.get("list_of_rare_earth_compounds")
    if not isinstance(compounds, list):
        raise ValueError("list_of_rare_earth_compounds must be an array")
    if require_compounds and not compounds:
        raise ValueError("Empty card: rare-earth CCDC metadata/audit entries require compound records; inspect the article before saving")
    if (not isinstance(data.get("title"), str) or
            data["title"].strip().lower() in {"", "reading extractor skill and article sources", "untitled", "unknown"}):
        raise ValueError("Placeholder or missing article title")
    expected = set(expected_ccdc or [])
    present = {str(number).strip() for item in compounds if isinstance(item, dict)
               for number in (item.get("ccdc_numbers") or [])}
    absent = sorted(expected - present)
    if absent:
        raise ValueError(f"Reviewed local CIFs still missing from card for {doi}: {', '.join(absent)}")

    reasons: list[str] = []
    for index, compound in enumerate(compounds, start=1):
        if not isinstance(compound, dict):
            raise ValueError(f"compound {index} must be an object")
        require_keys(compound, ["compound_label", "compound_name", "formula", "ccdc_numbers", "ccdc_refcodes", "material_class", "synthesis", "properties", "source_locations"], f"compound {index}")

        synthesis = compound["synthesis"]
        require_keys(synthesis, ["main_text_has_explicit_synthesis", "si_used", "procedure", "reagents"], f"compound {index}.synthesis")
        reagents = synthesis.get("reagents") or []
        has_named_reagent = any(isinstance(r, dict) and str(r.get("name") or "").strip() for r in reagents)
        has_amount = any(isinstance(r, dict) and has_numerical_amount(r.get("amount")) for r in reagents)
        has_procedure = bool(str(synthesis.get("procedure") or "").strip())
        defensible_main_synthesis = has_named_reagent and has_amount and has_procedure

        # The deterministic rule wins over an optimistic model flag.
        if synthesis.get("main_text_has_explicit_synthesis") and not defensible_main_synthesis:
            synthesis["main_text_has_explicit_synthesis"] = False
        if synthesis.get("si_used") and not defensible_main_synthesis:
            synthesis["si_used"] = False

        label = compound.get("compound_label") or compound.get("formula") or compound.get("compound_name") or f"compound {index}"
        if not synthesis.get("main_text_has_explicit_synthesis") and not (synthesis.get("si_used") and defensible_main_synthesis):
            missing = []
            if not has_named_reagent:
                missing.append("named reagents")
            if not has_amount:
                missing.append("reagent amounts")
            if not has_procedure:
                missing.append("preparation procedure")
            detail = ", ".join(missing) if missing else "explicit main-text synthesis"
            reasons.append(f"{label}: missing {detail}")

        properties = compound["properties"]
        require_keys(properties, ["reported", "property_type", "summary", "measurements"], f"compound {index}.properties")
        ptype = properties.get("property_type")
        if ptype not in PROPERTY_TYPES:
            raise ValueError(f"compound {index}: invalid property_type {ptype!r}")
        if not properties.get("reported"):
            properties["property_type"] = "none"
            properties["measurements"] = []
        elif ptype == "none":
            raise ValueError(f"compound {index}: reported=true cannot use property_type=none")

        allowed_measurement_types = {"magnetic", "optical"}
        if properties["property_type"] != "both":
            allowed_measurement_types = {properties["property_type"]}
        for measurement in properties.get("measurements") or []:
            if measurement.get("property_type") not in allowed_measurement_types:
                raise ValueError(f"compound {index}: measurement type conflicts with property_type")
    # SI requirement is workflow state: keep it only in the CSV ledger, not in the card.
    data.pop("needs_si", None)
    data.pop("si_reason", None)
    return data, reasons


def atomic_json_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def update_si_ledger(path: Path, doi: str, card_path: Path, reasons: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: dict[str, dict[str, str]] = {}
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                key = normalize_doi(row.get("doi"))
                if key:
                    rows[key] = row

    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    if reasons:
        rows[doi] = {
            "doi": doi,
            "status": "pending",
            "reason": "; ".join(reasons),
            "card_path": str(card_path.resolve()),
            "updated_at": now,
        }
    else:
        rows.pop(doi, None)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        fields = ["doi", "status", "reason", "card_path", "updated_at"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows[key] for key in sorted(rows))


def update_queue(path: Path, doi: str) -> None:
    if not path.exists():
        return
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        rows = list(reader)
    for row in rows:
        if normalize_doi(row.get("doi")) == doi:
            row["status"] = "completed"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_json", type=Path)
    parser.add_argument("--doi")
    parser.add_argument("--expected-ccdc", action="append", default=[])
    parser.add_argument("--require-compounds", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cards-dir", type=Path, default=ROOT / "data" / "extracted_cards")
    parser.add_argument("--si-ledger", type=Path, default=ROOT / "data" / "process_csv" / "si_required.csv")
    parser.add_argument("--queue", type=Path, default=ROOT / "data" / "process_csv" / "extraction_queue.csv")
    args = parser.parse_args()

    with args.input_json.open(encoding="utf-8-sig") as handle:
        data = json.load(handle)
    data, reasons = validate_and_derive(data, args.doi, args.expected_ccdc, args.require_compounds)
    output = args.output or (args.cards_dir / f"{safe_stem(data['doi'])}.json")
    atomic_json_write(output, data)
    update_si_ledger(args.si_ledger, data["doi"], output, reasons)
    update_queue(args.queue, data["doi"])
    print(f"saved: {output}")
    print(f"needs_si: {bool(reasons)} (recorded only in SI ledger)")
    if reasons:
        print(f"reason: {'; '.join(reasons)}")


if __name__ == "__main__":
    main()

