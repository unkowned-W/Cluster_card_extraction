#!/usr/bin/env python3
"""Validate review knowledge cards and maintain the DOI-to-card CSV index."""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CARDS_DIR = ROOT / "data" / "review_knowledge_cards"
INDEX = ROOT / "data" / "process_csv" / "review_knowledge_index.csv"
CATEGORIES = {
    "synthesis_strategy", "structural_pattern", "structure_property_relationship",
    "mechanistic_interpretation", "method_comparison", "limitation", "other",
}
BASES = {"review_synthesis", "cited_example"}
TOP_KEYS = {"doi", "title", "md_file", "cards"}
CARD_KEYS = {"category", "claim", "explanation", "scope", "conditions",
             "caveats", "evidence_locations", "basis"}
INDEX_FIELDS = ["doi", "title", "card_id", "card_file", "category", "claim",
                "md_file", "evidence_locations"]


def normalize_doi(value: str) -> str:
    doi = value.strip().lower()
    doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", doi)
    return doi.rstrip(". ,;")


def safe_stem(doi: str) -> str:
    return re.sub(r"[^A-Za-z0-9.\-]+", "_", doi).strip("._")


def _required_string(value, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where} must be a non-empty string")
    return value.strip()


def validate(data: dict, root: Path = ROOT) -> tuple[str, Path, list[dict]]:
    if not isinstance(data, dict) or set(data) != TOP_KEYS:
        raise ValueError(f"Input object must have exactly these fields: {sorted(TOP_KEYS)}")
    doi = normalize_doi(_required_string(data["doi"], "doi"))
    if not re.fullmatch(r"10\.\d{4,9}/\S+", doi, flags=re.I):
        raise ValueError(f"Invalid DOI: {doi}")
    title = _required_string(data["title"], "title")
    source = Path(_required_string(data["md_file"], "md_file"))
    source = (source if source.is_absolute() else root / source).resolve()
    if not source.is_file() or source.suffix.lower() != ".md":
        raise ValueError(f"Markdown source does not exist: {source}")
    cards = data["cards"]
    if not isinstance(cards, list):
        raise ValueError("cards must be an array")
    validated = []
    for i, card in enumerate(cards, 1):
        if not isinstance(card, dict) or set(card) != CARD_KEYS:
            raise ValueError(f"Card {i} must have exactly these fields: {sorted(CARD_KEYS)}")
        result = dict(card)
        for field in ("claim", "explanation", "scope"):
            result[field] = _required_string(result[field], f"Card {i}.{field}")
        for field in ("conditions", "caveats"):
            if result[field] is not None:
                result[field] = _required_string(result[field], f"Card {i}.{field}")
        if result["category"] not in CATEGORIES or result["basis"] not in BASES:
            raise ValueError(f"Card {i}: invalid category or basis")
        locations = result["evidence_locations"]
        if not isinstance(locations, list) or not locations:
            raise ValueError(f"Card {i}: evidence_locations must be a nonempty list")
        result["evidence_locations"] = [
            _required_string(location, f"Card {i}.evidence_locations") for location in locations
        ]
        validated.append({"card_id": f"{safe_stem(doi)}_{i}", "doi": doi,
                          "title": title, "md_file": str(source), **result})
    return doi, source, validated


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".review_", suffix=".tmp", dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig" if path.suffix == ".csv" else "utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def save(data: dict, *, root: Path = ROOT, replace: bool = False) -> list[Path]:
    doi, _, cards = validate(data, root)
    out_dir = root / "data" / "review_knowledge_cards"
    index = root / "data" / "process_csv" / "review_knowledge_index.csv"
    out_dir.mkdir(parents=True, exist_ok=True)
    index.parent.mkdir(parents=True, exist_ok=True)
    old_rows = []
    if index.exists():
        with index.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != INDEX_FIELDS:
                raise ValueError("Existing index has an unexpected schema; leave it untouched")
            old_rows = list(reader)
    previous = [row for row in old_rows if row["doi"] == doi]
    # Only delete card files from the dedicated directory, never paths from CSV.
    old_paths = {out_dir / (row["card_id"] + ".json") for row in previous}
    paths = [out_dir / (card["card_id"] + ".json") for card in cards]
    if (previous or any(p.exists() for p in paths)) and not replace:
        raise FileExistsError(f"DOI {doi} already has saved cards; review them and use --replace deliberately")
    if replace:
        for old in old_paths:
            if old.exists():
                existing = json.loads(old.read_text(encoding="utf-8-sig"))
                if existing.get("doi") != doi:
                    raise ValueError(f"Refusing to replace another DOI's card: {old}")
        for dest in paths:
            if dest.exists() and dest not in old_paths:
                existing = json.loads(dest.read_text(encoding="utf-8-sig"))
                if existing.get("doi") != doi:
                    raise ValueError(f"Refusing to overwrite another DOI's card: {dest}")
    for dest, card in zip(paths, cards):
        _atomic_text(dest, json.dumps(card, ensure_ascii=False, indent=2) + "\n")
    new_rows = [row for row in old_rows if row["doi"] != doi]
    for dest, card in zip(paths, cards):
        new_rows.append({"doi": doi, "title": card["title"], "card_id": card["card_id"],
                         "card_file": str(dest.relative_to(root)).replace("\\", "/"),
                         "category": card["category"], "claim": card["claim"],
                         "md_file": card["md_file"],
                         "evidence_locations": " | ".join(card["evidence_locations"])})
    from io import StringIO
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=INDEX_FIELDS)
    writer.writeheader()
    writer.writerows(new_rows)
    _atomic_text(index, buffer.getvalue())
    for stale in old_paths - set(paths):
        stale.unlink(missing_ok=True)
    return paths


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Extracted review JSON")
    parser.add_argument("--replace", action="store_true", help="Replace cards already indexed for this DOI")
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8-sig"))
    saved = save(data, replace=args.replace)
    print(f"Saved {len(saved)} review knowledge cards to {CARDS_DIR}")
    print(f"Index: {INDEX}")
