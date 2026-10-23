# -*- coding: utf-8 -*-
"""Build one extraction queue row per main-article Markdown file.

Supporting-information Markdown files are attached to their article row, not
queued as separate papers. Unmatched article Markdown is still queued and
written to data/process_csv/md_without_ccdc.csv.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
import sys
sys.path.insert(0, str(ROOT / "scripts"))
from ccdc_data import doi_filename, normalize_doi as preserve_doi


def normalize_doi(value: str | None) -> str:
    return preserve_doi(value or "").lower()


def compact_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def guess_doi_from_stem(stem: str) -> str:
    if "_" in stem:
        prefix, rest = stem.split("_", 1)
        if prefix.startswith("10."):
            return f"{prefix}/{rest}"
    return stem


def choose_metadata(path: Path | None) -> Path:
    if path:
        return path
    preferred = ROOT / "data" / "structures.csv"
    if preferred.exists():
        return preferred
    fallback = ROOT / "data" / "cluster_complex.csv"
    if fallback.exists():
        return fallback
    raise FileNotFoundError("Neither data/structures.csv nor data/cluster_complex.csv exists")


def read_metadata(path: Path) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "doi" not in {name.lower() for name in reader.fieldnames}:
            raise ValueError(f"Metadata CSV has no DOI column: {path}")
        doi_col = next(name for name in reader.fieldnames if name.lower() == "doi")
        for row in reader:
            doi = normalize_doi(row.get(doi_col))
            if doi:
                grouped[doi].append({key: (value or "").strip() for key, value in row.items()})
    return grouped


def build_metadata_index(grouped: dict[str, list[dict[str, str]]]) -> tuple[dict[str, str], dict[str, list[str]]]:
    exact: dict[str, str] = {}
    compact: dict[str, list[str]] = defaultdict(list)
    for doi in grouped:
        stem = Path(doi_filename(doi)).stem.lower()
        exact[stem] = doi
        compact[compact_key(stem)].append(doi)
        compact[compact_key(doi)].append(doi)
    return exact, compact


def resolve_doi(stem: str, exact: dict[str, str], compact: dict[str, list[str]]) -> str:
    key = stem.lower()
    if key in exact:
        return exact[key]
    packed = compact_key(stem)
    if packed in exact:
        return exact[packed]
    hits = list(dict.fromkeys(compact.get(packed, [])))
    if len(hits) == 1:
        return hits[0]
    return guess_doi_from_stem(stem)


def list_si_files(si_dir: Path) -> list[Path]:
    if not si_dir.exists():
        return []
    return [path for path in si_dir.rglob("*") if path.is_file()]


def find_si_files(si_files: list[Path], doi: str, stem: str) -> list[str]:
    keys = {stem.lower(), Path(doi_filename(doi)).stem.lower()}
    matches = []
    for path in si_files:
        name = path.stem.lower()
        if any(name == key or name.startswith(key + "_") for key in keys):
            matches.append(str(path.resolve()))
    return sorted(set(matches))


def card_needs_review(card_path: Path, doi: str, expected: set[str]) -> bool:
    if not card_path.is_file():
        return True
    try:
        card = json.loads(card_path.read_text(encoding="utf-8-sig"))
        compounds = card.get("list_of_rare_earth_compounds")
        if not isinstance(compounds, list):
            return True
        if expected and not compounds:
            return True
        if (card.get("title") or "").strip().lower() in {"", "reading extractor skill and article sources", "untitled", "unknown"}:
            return True
        present = {str(number).strip() for compound in compounds if isinstance(compound, dict)
                   for number in (compound.get("ccdc_numbers") or [])}
        return bool(expected - present)
    except (OSError, ValueError, TypeError):
        return True


def build_queue(
    metadata_csv: Path,
    pdf_dir: Path,
    md_dir: Path,
    si_dir: Path,
    output_csv: Path,
    cards_dir: Path,
    missing_csv: Path | None = None,
    *,
    write_files: bool = True,
) -> list[dict[str, str]]:
    grouped = read_metadata(metadata_csv)
    exact, compact = build_metadata_index(grouped)
    missing_path = Path(missing_csv) if missing_csv else ROOT / "data" / "process_csv" / "md_without_ccdc.csv"

    md_files = sorted(
        (path for path in md_dir.glob("*.md")
         if not re.search(r"_si(?:[_-]|$)", path.stem, re.IGNORECASE)),
        key=lambda path: path.name.lower(),
    )
    si_files = [
        *list_si_files(si_dir),
        *(path for path in md_dir.glob("*.md")
          if re.search(r"_si(?:[_-]|$)", path.stem, re.IGNORECASE)),
    ]
    metadata_numbers_by_doi = {doi: {item["ccdc_number"] for item in items if item.get("ccdc_number", "").isdigit()}
                               for doi, items in grouped.items()}
    rows: list[dict[str, str]] = []
    missing_rows: list[dict[str, str]] = []

    for md_path in md_files:
        stem = md_path.stem
        doi = resolve_doi(stem, exact, compact)
        metadata_rows = grouped.get(doi, [])
        pdf_path = pdf_dir / f"{stem}.pdf"
        card_path = cards_dir / f"{stem}.json"
        rows.append({
            "doi": doi,
            "pdf_path": str(pdf_path.resolve()) if pdf_path.is_file() else "",
            "md_path": str(md_path.resolve()),
            "source_mode": "markdown",
            "si_paths": json.dumps(find_si_files(si_files, doi, stem), ensure_ascii=False),
            "metadata_rows": json.dumps(metadata_rows, ensure_ascii=False),
            "card_path": str(card_path.resolve()),
            "status": "pending" if card_needs_review(card_path, doi, metadata_numbers_by_doi.get(doi, set())) else "completed",
        })
        if not metadata_rows:
            missing_rows.append({
                "doi": doi,
                "md_name": md_path.name,
                "md_path": str(md_path.resolve()),
                "pdf_path": str(pdf_path.resolve()) if pdf_path.is_file() else "",
            })

    fieldnames = ["doi", "pdf_path", "md_path", "source_mode", "si_paths", "metadata_rows", "card_path", "status"]
    if write_files:
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        cards_dir.mkdir(parents=True, exist_ok=True)
        with output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        missing_path.parent.mkdir(parents=True, exist_ok=True)
        with missing_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["doi", "md_name", "md_path", "pdf_path"])
            writer.writeheader()
            writer.writerows(missing_rows)

    matched = len(rows) - len(missing_rows)
    missing_pdf = sum(1 for row in rows if not row["pdf_path"])
    print(f"metadata: {metadata_csv}")
    print(f"Markdown 总数: {len(md_files)}")
    print(f"进入队列: {len(rows)}")
    print(f"已匹配 CCDC: {matched}")
    print(f"无 CCDC: {len(missing_rows)} -> {missing_path}")
    print(f"无对应 PDF: {missing_pdf}")
    print(f"pending: {sum(row['status'] == 'pending' for row in rows)}")
    if write_files:
        print(f"queue: {output_csv}")
        print(f"missing metadata report: {missing_path}")
    else:
        print(f"Preview only; no files written. Target queue: {output_csv}")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--pdf-dir", type=Path, default=ROOT / "documents" / "pdf")
    parser.add_argument("--md-dir", type=Path, default=ROOT / "documents" / "md")
    parser.add_argument("--si-dir", type=Path, default=ROOT / "documents" / "si")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "process_csv" / "extraction_queue.csv")
    parser.add_argument("--cards-dir", type=Path, default=ROOT / "data" / "extracted_cards")
    parser.add_argument("--missing", type=Path, default=ROOT / "data" / "process_csv" / "md_without_ccdc.csv")
    parser.add_argument("--preview", action="store_true", help="Build the queue in memory without writing files")
    args = parser.parse_args()
    build_queue(
        choose_metadata(args.metadata),
        args.pdf_dir,
        args.md_dir,
        args.si_dir,
        args.output,
        args.cards_dir,
        missing_csv=args.missing,
        write_files=not args.preview,
    )


if __name__ == "__main__":
    main()
