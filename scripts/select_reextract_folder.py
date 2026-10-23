"""Select article extraction queue rows using DOI-named files in a folder."""
from __future__ import annotations

import csv
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def select_rows(folder: Path, queue_source: Path | list[dict[str, str]]) -> tuple[list[dict[str, str]], list[str]]:
    folder = Path(folder)
    if not folder.is_dir():
        raise NotADirectoryError(f"Re-extraction folder does not exist: {folder}")
    if isinstance(queue_source, (str, Path)):
        with Path(queue_source).open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    else:
        rows = list(queue_source)

    by_stem: dict[str, dict[str, str]] = {}
    for row in rows:
        for column in ("md_path", "pdf_path", "card_path"):
            name = Path(row.get(column) or "").stem.lower()
            if not name:
                continue
            previous = by_stem.get(name)
            if previous and previous["doi"].lower() != row["doi"].lower():
                raise ValueError(f"Ambiguous DOI filename in queue: {name}")
            by_stem[name] = row

    selected: dict[str, dict[str, str]] = {}
    unmatched: list[str] = []
    files = sorted((path for path in folder.rglob("*") if path.is_file()
                    and path.suffix.lower() in {".md", ".pdf"}), key=lambda path: str(path).lower())
    for path in files:
        row = by_stem.get(path.stem.lower())
        if row is None:
            unmatched.append(str(path))
            continue
        doi = row["doi"].strip().lower()
        target = selected.setdefault(doi, dict(row, md_path="", pdf_path=""))
        column = "md_path" if path.suffix.lower() == ".md" else "pdf_path"
        if target[column] and Path(target[column]).resolve() != path.resolve():
            raise ValueError(f"Multiple {path.suffix} files for {doi}: {target[column]}, {path}")
        target[column] = str(path.resolve())

    for row in selected.values():
        row["source_mode"] = "markdown" if row["md_path"] else "pdf_fallback"
    return list(selected.values()), unmatched


def merge_status(rows: list[dict[str, str]], path: Path) -> list[dict[str, str]]:
    previous: dict[str, dict[str, str]] = {}
    if path.is_file():
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for entry in csv.DictReader(handle):
                doi = (entry.get("doi") or "").strip().lower()
                if doi in previous:
                    raise ValueError(f"Duplicate DOI in re-extraction CSV: {doi}")
                previous[doi] = entry
    merged = []
    for row in rows:
        saved = previous.get(row["doi"].strip().lower(), {})
        status = saved.get("reextract_status") or "pending"
        if status not in {"pending", "success", "failed"}:
            raise ValueError(f"Invalid re-extraction status for {row['doi']}: {status}")
        merged.append(dict(row, reextract_status=status,
                           reextract_updated_at=saved.get("reextract_updated_at") or ""))
    return merged


def record_result(
    path: Path,
    doi: str,
    success: bool,
    *,
    status_field: str = "reextract_status",
    updated_field: str = "reextract_updated_at",
) -> None:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row.setdefault(status_field, "pending")
        row.setdefault(updated_field, "")
    matches = [row for row in rows if row["doi"].strip().lower() == doi.strip().lower()]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one re-extraction row for {doi}")
    matches[0][status_field] = "success" if success else "failed"
    matches[0][updated_field] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_queue(path, rows)


def write_queue(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        raise ValueError("No DOI-named article files match the extraction queue")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8-sig", newline="",
                                         dir=path.parent, prefix=path.name + ".", suffix=".tmp",
                                         delete=False) as handle:
            temporary = Path(handle.name)
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
