# -*- coding: utf-8 -*-
"""Step 1: filter a CCDC refcode-list .gcd file and write a smaller .gcd."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Sequence

try:
    from .ccdc_data import lookup_records, matches_formula, read_gcd, write_gcd
except ImportError:
    from ccdc_data import lookup_records, matches_formula, read_gcd, write_gcd

ROOT = Path(__file__).resolve().parent.parent


def run(
    gcd_path: str | Path,
    out_gcd: str | Path | None = None,
    report_csv: str | Path | None = None,
    must_contain: Iterable[str] = (),
    forbid: Iterable[str] = (),
    element: Sequence[str] = (),
    metals: str = "",
    ignore_solvents: bool = False,
    exclude_formula_n: bool = False,
    contains: str = "",
    regex: str = "",
) -> Path:
    source = Path(gcd_path)
    output = Path(out_gcd) if out_gcd else ROOT / "data" / "filtered.gcd"
    report = Path(report_csv) if report_csv else output.with_name(output.stem + "_filter_report.csv")

    refcodes = read_gcd(source)
    records = lookup_records(refcodes)
    kept, rows = [], []
    for refcode in refcodes:
        formula = records[refcode]["formula"]
        ok, reason = matches_formula(
            formula,
            must_contain=must_contain,
            forbid=forbid,
            element_rules=element,
            metals=metals,
            ignore_solvents=ignore_solvents,
            exclude_formula_n=exclude_formula_n,
            contains=contains,
            regex=regex,
        )
        if ok:
            kept.append(refcode)
        rows.append({"refcode": refcode, "formula": formula, "kept": ok, "reason": reason})

    write_gcd(output, kept)
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["refcode", "formula", "kept", "reason"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"输入 refcode: {len(refcodes)}")
    print(f"筛选后 refcode: {len(kept)}")
    print(f"GCD: {output}")
    print(f"筛选报告: {report}")
    return output
