# -*- coding: utf-8 -*-
"""Check converted Markdown quality and isolate suspicious files.

MinerU without OCR often yields empty or tiny Markdown for scanned PDFs.
This step flags those DOIs, writes a CSV report, and copies the PDFs and
Markdown files into isolation folders for manual inspection.
"""
from __future__ import annotations

import argparse
import csv
import re
import shutil
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
TABLE_RE = re.compile(r"<table\b[\s\S]*?</table>", re.I)
HTML_RE = re.compile(r"<[^>]+>")
LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def normalize_doi(value: str | None) -> str:
    doi = (value or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "http://dx.doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix):].strip()
            break
    return doi.rstrip(". ,;")


def doi_filename_stem(doi: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", normalize_doi(doi), flags=re.ASCII).strip("._")


def guess_doi_from_stem(stem: str) -> str:
    if "_" in stem:
        prefix, rest = stem.split("_", 1)
        if prefix.startswith("10."):
            return f"{prefix}/{rest}"
    return stem


def _load_doi_lookup(metadata_csv: Path | None) -> dict[str, str]:
    lookup: dict[str, str] = {}
    if metadata_csv is None or not metadata_csv.is_file():
        return lookup
    with metadata_csv.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            return lookup
        doi_col = next((name for name in reader.fieldnames if name.lower() == "doi"), None)
        if not doi_col:
            return lookup
        for row in reader:
            doi = normalize_doi(row.get(doi_col))
            if doi:
                lookup[doi_filename_stem(doi).lower()] = doi
    return lookup


def _usable_text(markdown: str) -> str:
    text = IMAGE_RE.sub(" ", markdown)
    text = TABLE_RE.sub(" ", text)
    text = HTML_RE.sub(" ", text)
    text = LINK_RE.sub(r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def _assess_markdown(
    md_path: Path,
    *,
    min_md_bytes: int,
    min_text_chars: int,
) -> tuple[list[str], int, int, int]:
    reasons: list[str] = []
    if not md_path.is_file():
        return ["missing_md"], 0, 0, 0

    md_bytes = md_path.stat().st_size
    raw = md_path.read_text(encoding="utf-8", errors="ignore")
    if md_bytes <= 0 or not raw.strip():
        return ["empty_md"], md_bytes, 0, 0

    image_count = len(IMAGE_RE.findall(raw))
    text_chars = len(_usable_text(raw))
    if md_bytes < min_md_bytes:
        reasons.append("md_too_small")
    if text_chars < min_text_chars:
        reasons.append("text_too_short")
    if image_count >= 3 and text_chars < min_text_chars:
        reasons.append("mostly_images")
    return reasons, md_bytes, text_chars, image_count


def _copy_if_needed(src: Path, dest: Path) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return str(dest)


def run(
    pdf_dir: str | Path,
    md_dir: str | Path,
    isolate_dir: str | Path | None = None,
    md_isolate_dir: str | Path | None = None,
    metadata_csv: str | Path | None = None,
    report_csv: str | Path | None = None,
    min_md_bytes: int = 4000,
    min_text_chars: int = 1200,
    copy_pdfs: bool = True,
    copy_mds: bool = True,
) -> list[dict[str, str]]:
    pdf_dir = Path(pdf_dir)
    md_dir = Path(md_dir)
    isolate_dir = Path(isolate_dir) if isolate_dir else pdf_dir / "isolated_tiny_md"
    md_isolate_dir = Path(md_isolate_dir) if md_isolate_dir else md_dir / "isolated_tiny_md"
    metadata_path = Path(metadata_csv) if metadata_csv else ROOT / "data" / "cluster_complex.csv"
    report_path = Path(report_csv) if report_csv else ROOT / "data" / "md_quality_issues.csv"

    doi_lookup = _load_doi_lookup(metadata_path)
    pdfs = sorted(pdf_dir.glob("*.pdf"), key=lambda p: p.name.lower())
    issues: list[dict[str, str]] = []
    reason_counts: Counter[str] = Counter()

    for pdf_path in pdfs:
        md_path = md_dir / f"{pdf_path.stem}.md"
        reasons, md_bytes, text_chars, image_count = _assess_markdown(
            md_path,
            min_md_bytes=min_md_bytes,
            min_text_chars=min_text_chars,
        )
        if not reasons:
            continue

        doi = doi_lookup.get(pdf_path.stem.lower()) or guess_doi_from_stem(pdf_path.stem)
        isolated_pdf = ""
        isolated_md = ""
        if copy_pdfs:
            isolated_pdf = _copy_if_needed(pdf_path, isolate_dir / pdf_path.name)
        if copy_mds and md_path.is_file():
            isolated_md = _copy_if_needed(md_path, md_isolate_dir / md_path.name)

        issues.append({
            "doi": doi,
            "pdf_name": pdf_path.name,
            "pdf_path": str(pdf_path.resolve()),
            "md_path": str(md_path) if md_path.exists() else "",
            "md_bytes": str(md_bytes),
            "text_chars": str(text_chars),
            "image_count": str(image_count),
            "reasons": ";".join(reasons),
            "isolated_pdf": isolated_pdf,
            "isolated_md": isolated_md,
        })
        reason_counts.update(reasons)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "doi", "pdf_name", "pdf_path", "md_path", "md_bytes", "text_chars",
        "image_count", "reasons", "isolated_pdf", "isolated_md",
    ]
    with report_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(issues)

    print(f"PDF 总数: {len(pdfs)}")
    print(f"Markdown 正常: {len(pdfs) - len(issues)}")
    print(f"异常件数: {len(issues)}")
    if reason_counts:
        summary = "，".join(f"{key}={value}" for key, value in sorted(reason_counts.items()))
        print(f"原因统计: {summary}")
    print(f"异常 DOI 清单: {report_path}")
    if copy_mds:
        print(f"请检查隔离的 Markdown: {md_isolate_dir}")
    if copy_pdfs:
        print(f"对应 PDF 副本: {isolate_dir}")

    unique_dois = []
    seen = set()
    for row in issues:
        doi = row["doi"]
        if doi not in seen:
            seen.add(doi)
            unique_dois.append(doi)
    print(f"异常 DOI 数: {len(unique_dois)}")
    preview = unique_dois[:50]
    for doi in preview:
        print(f"  {doi}")
    if len(unique_dois) > len(preview):
        print(f"  ... 其余 {len(unique_dois) - len(preview)} 条见 CSV")
    return issues


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf-dir", type=Path, default=ROOT / "documents" / "pdf")
    parser.add_argument("--md-dir", type=Path, default=ROOT / "documents" / "md")
    parser.add_argument("--isolate-dir", type=Path)
    parser.add_argument("--md-isolate-dir", type=Path)
    parser.add_argument("--metadata", type=Path, default=ROOT / "data" / "cluster_complex.csv")
    parser.add_argument("--report", type=Path, default=ROOT / "data" / "md_quality_issues.csv")
    parser.add_argument("--min-md-bytes", type=int, default=4000)
    parser.add_argument("--min-text-chars", type=int, default=1200)
    parser.add_argument("--no-copy", action="store_true")
    args = parser.parse_args()
    copy = not args.no_copy
    run(
        args.pdf_dir,
        args.md_dir,
        isolate_dir=args.isolate_dir,
        md_isolate_dir=args.md_isolate_dir,
        metadata_csv=args.metadata,
        report_csv=args.report,
        min_md_bytes=args.min_md_bytes,
        min_text_chars=args.min_text_chars,
        copy_pdfs=copy,
        copy_mds=copy,
    )


if __name__ == "__main__":
    main()
