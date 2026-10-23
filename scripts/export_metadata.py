# -*- coding: utf-8 -*-
"""Step 2: export refcode, DOI, formula and CCDC number from a filtered .gcd."""
from __future__ import annotations

import csv
from pathlib import Path

try:
    from .ccdc_data import lookup_records, read_gcd
except ImportError:
    from ccdc_data import lookup_records, read_gcd

ROOT = Path(__file__).resolve().parent.parent


def run(gcd_path: str | Path, out_csv: str | Path | None = None) -> Path:
    source = Path(gcd_path)
    output = Path(out_csv) if out_csv else ROOT / "data" / "structures.csv"
    refcodes = read_gcd(source)
    records = lookup_records(refcodes)
    rows = [records[code] for code in refcodes]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["refcode", "doi", "formula", "ccdc_number"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"导出记录: {len(rows)}")
    print(f"有 DOI: {sum(bool(row['doi']) for row in rows)}")
    print(f"唯一 DOI: {len({row['doi'].lower() for row in rows if row['doi']})}")
    print(f"CSV: {output}")
    return output
