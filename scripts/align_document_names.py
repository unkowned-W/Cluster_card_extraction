# -*- coding: utf-8 -*-
"""Rename PDF/Markdown/SI files so names follow CCDC metadata DOIs."""
from __future__ import annotations

import csv
import re
from pathlib import Path

from ccdc_data import doi_filename, normalize_doi

ROOT = Path(__file__).resolve().parent.parent


def compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def first_raw_dois(csv_path: Path) -> dict[str, str]:
    """Map lowercase DOI -> first metadata spelling."""
    mapping: dict[str, str] = {}
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        doi_col = next(name for name in (reader.fieldnames or []) if name.lower() == "doi")
        for row in reader:
            raw = normalize_doi(row.get(doi_col) or "")
            if not raw:
                continue
            mapping.setdefault(raw.lower(), raw)
    return mapping


def index_by_stem(folder: Path, pattern: str) -> dict[str, Path]:
    if not folder.exists():
        return {}
    return {path.stem: path for path in folder.glob(pattern)}


def unique_match(canonical: str, files: dict[str, Path]) -> Path | None:
    if canonical in files:
        return files[canonical]
    lower_hits = [path for stem, path in files.items() if stem.lower() == canonical.lower()]
    if len(lower_hits) == 1:
        return lower_hits[0]
    packed = compact(canonical)
    compact_hits = [path for stem, path in files.items() if compact(stem) == packed]
    if len(compact_hits) == 1:
        return compact_hits[0]
    prefix_hits = [
        path for stem, path in files.items()
        if packed.startswith(compact(stem)) and len(compact(stem)) >= 20
    ]
    if len(prefix_hits) == 1:
        return prefix_hits[0]
    return None


def rename_pair(src: Path, dest: Path) -> str:
    if not src.exists():
        return "missing"
    if src.parent == dest.parent and src.name == dest.name:
        return "already"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.parent == dest.parent and src.name.lower() == dest.name.lower() and src.name != dest.name:
        tmp = src.with_name(src.name + ".__rename_tmp__")
        src.rename(tmp)
        tmp.rename(dest)
        return "case"
    if dest.exists() and src.resolve() != dest.resolve():
        return "conflict"
    src.rename(dest)
    return "renamed"


def iter_related(old_stem: str, new_stem: str) -> list[tuple[Path, Path]]:
    pairs: list[tuple[Path, Path]] = []
    folders = [
        ROOT / "documents" / "pdf",
        ROOT / "documents" / "md",
        ROOT / "documents" / "pdf" / "isolated_tiny_md",
        ROOT / "documents" / "md" / "isolated_tiny_md",
        ROOT / "data" / "extracted_cards",
        ROOT / "data" / "extraction_logs",
    ]
    for folder in folders:
        if not folder.exists():
            continue
        for src in folder.glob(old_stem + ".*"):
            pairs.append((src, folder / (new_stem + src.suffix)))
        for src in folder.glob(old_stem + ".*.*"):
            extra = src.name[len(old_stem):]
            pairs.append((src, folder / (new_stem + extra)))
    si_dir = ROOT / "documents" / "si"
    if si_dir.exists():
        for src in si_dir.rglob("*"):
            if not src.is_file():
                continue
            name = src.name
            if name == old_stem or name.startswith(old_stem + ".") or name.startswith(old_stem + "_"):
                pairs.append((src, src.with_name(new_stem + name[len(old_stem):])))
    # de-duplicate
    seen = set()
    unique = []
    for src, dest in pairs:
        key = (str(src), str(dest))
        if key not in seen:
            seen.add(key)
            unique.append((src, dest))
    return unique


def run(metadata_csv: Path | None = None) -> None:
    metadata_csv = metadata_csv or ROOT / "data" / "cluster_complex.csv"
    raw_map = first_raw_dois(metadata_csv)
    pdfs = index_by_stem(ROOT / "documents" / "pdf", "*.pdf")
    log_rows: list[dict[str, str]] = []
    missing_rows: list[dict[str, str]] = []

    for key, raw in raw_map.items():
        canonical = Path(doi_filename(raw)).stem
        match = unique_match(canonical, pdfs)
        if match is None:
            missing_rows.append({"doi": raw, "expected_pdf": canonical + ".pdf", "found": ""})
            continue
        if match.stem == canonical:
            log_rows.append({"doi": raw, "old_stem": match.stem, "new_stem": canonical, "status": "already"})
            continue
        status = "ok"
        details = []
        for src, dest in iter_related(match.stem, canonical):
            result = rename_pair(src, dest)
            details.append(f"{src.name}->{dest.name}:{result}")
            if result == "conflict":
                status = "conflict"
        pdfs = index_by_stem(ROOT / "documents" / "pdf", "*.pdf")
        log_rows.append({
            "doi": raw,
            "old_stem": match.stem,
            "new_stem": canonical,
            "status": status,
            "details": " | ".join(details),
        })
        print(f"{status}: {match.stem} -> {canonical}")

    log_path = ROOT / "data" / "filename_align_log.csv"
    miss_path = ROOT / "data" / "metadata_missing_pdf.csv"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["doi", "old_stem", "new_stem", "status", "details"])
        writer.writeheader()
        writer.writerows(log_rows)
    with miss_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["doi", "expected_pdf", "found"])
        writer.writeheader()
        writer.writerows(missing_rows)

    renamed = sum(1 for row in log_rows if row["status"] in {"ok", "case"} and row["old_stem"] != row["new_stem"])
    print(f"metadata DOIs: {len(raw_map)}")
    print(f"already matching: {sum(1 for row in log_rows if row['status']=='already')}")
    print(f"renamed: {renamed}")
    print(f"still missing PDF: {len(missing_rows)} -> {miss_path}")
    for row in missing_rows:
        print(f"  {row['doi']}")


if __name__ == "__main__":
    run()
