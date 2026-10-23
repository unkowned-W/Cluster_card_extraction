# -*- coding: utf-8 -*-
"""Shared CCDC/CSD helpers for the small four-step pipeline."""
from __future__ import annotations

import os
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Iterable, Sequence

ROOT = Path(__file__).resolve().parent.parent
_CSD_HOME = Path(os.environ.get("CSD_HOME", r"D:\CCDC"))
DEFAULT_CSD_DIR = Path(os.environ.get("CSD_DATA_DIR", _CSD_HOME / "ccdc-data" / "csd"))
REFCODE_RE = re.compile(r"^[A-Z]{6}(?:\d{2})?$", re.I)
ELEMENT_RE = re.compile(r"([A-Z][a-z]?)(?:\s*)(\d*(?:\.\d+)?)")
COMPONENT_RE = re.compile(r"^(\d+(?:\.\d+)?)\((.*)\)$")
FORMULA_N_RE = re.compile(r"(?:^|[\s,(])n(?:$|[\s,)])")
DOI_PREFIXES = ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/", "doi:")
METALS = {
    "Li", "Be", "Na", "Mg", "Al", "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
    "Ga", "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn", "Cs", "Ba",
    "La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu", "Hf", "Ta",
    "W", "Re", "Os", "Ir", "Pt", "Au", "Hg", "Tl", "Pb", "Bi", "Fr", "Ra", "Ac", "Th", "Pa", "U", "Np", "Pu",
}
COMMON_SOLVENT_COMPONENTS = {
    "H2 O1", "C1 H4 O1", "C2 H6 O1", "C2 H6 O1 S1", "C3 H7 N1 O1", "C3 H6 O1", "C4 H8 O1",
    "C4 H10 O1", "C5 H5 N1", "C6 H6", "C6 H14", "C7 H8", "C1 H2 Cl2", "C1 H1 Cl3", "C2 H3 N1",
}


def normalize_doi(raw: str) -> str:
    value = (raw or "").strip().replace("\\", "/")
    low = value.lower()
    for prefix in DOI_PREFIXES:
        if low.startswith(prefix):
            value = value[len(prefix):]
            break
    return value.strip().strip(" .;,<>)[]")


def doi_filename(doi: str, suffix: str = ".pdf") -> str:
    """Build a filesystem name from a DOI, preserving the metadata spelling."""
    safe = re.sub(r"[^\w.\-]+", "_", normalize_doi(doi), flags=re.ASCII).strip("._")
    return safe + suffix


def read_gcd(path: str | Path) -> list[str]:
    src = Path(path)
    text = src.read_text(encoding="utf-8-sig", errors="ignore")
    result, seen = [], set()
    for line in text.splitlines():
        token = line.strip().split()[0].upper() if line.strip() else ""
        if REFCODE_RE.fullmatch(token) and token not in seen:
            seen.add(token)
            result.append(token)
    return result


def write_gcd(path: str | Path, refcodes: Iterable[str]) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(refcodes) + "\n", encoding="utf-8")
    return out


def csd_sqlite_paths() -> list[Path]:
    if not DEFAULT_CSD_DIR.is_dir():
        return []
    paths = list(DEFAULT_CSD_DIR.glob("*.sqlite"))
    paths.sort(key=lambda p: ("ASER" not in p.name.upper(), "CIP" not in p.name.upper(), p.name), reverse=False)
    return paths


def lookup_records(refcodes: Sequence[str]) -> dict[str, dict[str, str]]:
    codes = list(dict.fromkeys(c.upper() for c in refcodes))
    records = {c: {"refcode": c, "ccdc_number": "", "doi": "", "formula": ""} for c in codes}
    if not codes:
        return records
    databases = csd_sqlite_paths()
    if not databases:
        raise FileNotFoundError(f"未找到 CSD SQLite 数据库: {DEFAULT_CSD_DIR}")
    unresolved = set(codes)
    for db in databases:
        if not unresolved:
            break
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        try:
            for start in range(0, len(codes), 700):
                batch = codes[start:start + 700]
                marks = ",".join("?" for _ in batch)
                cur = con.cursor()
                cur.execute(f"""
                    SELECT i.EntryIdentifier, d.CCDCNumber, f.Formula
                    FROM IDENTIFIER i
                    LEFT JOIN DEPOSITION_INFO d ON d.EntryId = i.Id
                    LEFT JOIN FORMULA f ON f.EntryId = i.Id
                    WHERE i.EntryIdentifier IN ({marks})
                """, batch)
                for ident, ccdc, formula in cur.fetchall():
                    ident = (ident or "").upper()
                    rec = records.get(ident)
                    if not rec:
                        continue
                    if ccdc and not rec["ccdc_number"]:
                        text = str(ccdc).replace(".0", "")
                        rec["ccdc_number"] = str(int(text)) if text.isdigit() else str(ccdc)
                    if formula and not rec["formula"]:
                        rec["formula"] = str(formula)
                cur.execute(f"""
                    SELECT i.EntryIdentifier, p.DOI, l.PublicationOrder
                    FROM IDENTIFIER i
                    JOIN ENTRY_PUBLICATION_LINKS l ON l.EntryId = i.Id
                    JOIN PUBLICATIONS p ON p.Id = l.PublicationId
                    WHERE i.EntryIdentifier IN ({marks})
                """, batch)
                best = {}
                for ident, doi, order in cur.fetchall():
                    ident = (ident or "").upper()
                    doi = normalize_doi(doi or "")
                    if doi and (ident not in best or (order is not None and (best[ident][1] is None or order < best[ident][1]))):
                        best[ident] = (doi, order)
                for ident, (doi, _order) in best.items():
                    if ident in records and not records[ident]["doi"]:
                        records[ident]["doi"] = doi
        finally:
            con.close()
        unresolved = {c for c in unresolved if not records[c]["formula"] and not records[c]["ccdc_number"]}
    return records


def formula_counts(formula: str, ignore_solvents: bool = False) -> Counter:
    """Count elements in comma-separated CSD formula components.

    CSD commonly writes solvates as ``3(C4 H8 O1)``.  The leading
    coefficient is applied to element counts, and solvent matching is done on
    the formula inside those parentheses.
    """
    counts: Counter = Counter()
    for raw_component in (formula or "").split(","):
        component = raw_component.strip()
        if not component:
            continue
        multiplier = 1.0
        match = COMPONENT_RE.fullmatch(component)
        if match:
            multiplier = float(match.group(1))
            component = match.group(2).strip()
        if ignore_solvents and component in COMMON_SOLVENT_COMPONENTS:
            continue
        for element, amount in ELEMENT_RE.findall(component):
            value = float(amount) if amount else 1.0
            counts[element] += multiplier * value
    return counts


def parse_range(text: str) -> tuple[float | None, float | None] | None:
    value = (text or "").strip()
    if not value:
        return None
    if value.startswith(">="):
        return float(value[2:]), None
    if value.startswith("<="):
        return None, float(value[2:])
    if "-" in value:
        lo, hi = value.split("-", 1)
        return float(lo), float(hi)
    number = float(value)
    return number, number


def in_range(value: float, bounds: tuple[float | None, float | None] | None) -> bool:
    if bounds is None:
        return True
    lo, hi = bounds
    return (lo is None or value >= lo) and (hi is None or value <= hi)


def parse_element_rule(rule: str) -> tuple[str, str, float]:
    match = re.fullmatch(r"([A-Z][a-z]?)(>=|<=|=|>|<)(\d+(?:\.\d+)?)", rule.strip())
    if not match:
        raise ValueError(f"无效元素规则: {rule}；示例 O>=10、Gd=4")
    return match.group(1), match.group(2), float(match.group(3))


def matches_formula(
    formula: str,
    must_contain: Iterable[str] = (),
    forbid: Iterable[str] = (),
    element_rules: Sequence[str] = (),
    metals: str = "",
    ignore_solvents: bool = False,
    exclude_formula_n: bool = False,
    contains: str = "",
    regex: str = "",
) -> tuple[bool, str]:
    must_contain = tuple(x.strip().capitalize() for x in must_contain if x.strip())
    forbid = tuple(x.strip().capitalize() for x in forbid if x.strip())
    needs_formula = bool(
        must_contain or forbid or element_rules or metals
        or ignore_solvents or exclude_formula_n or contains or regex
    )
    if not formula:
        return (False, "missing formula") if needs_formula else (True, "ok (formula missing; no filters)")
    if exclude_formula_n and FORMULA_N_RE.search(formula):
        return False, "formula contains n"
    if contains and contains.lower() not in formula.lower():
        return False, f"missing text {contains}"
    if regex and not re.search(regex, formula):
        return False, "regex mismatch"
    counts = formula_counts(formula, ignore_solvents=ignore_solvents)
    for element in must_contain:
        if counts[element] <= 0:
            return False, f"missing {element}"
    for element in forbid:
        if counts[element] > 0:
            return False, f"contains forbidden {element}"
    for rule in element_rules:
        element, op, target = parse_element_rule(rule)
        value = counts[element]
        ok = {">=": value >= target, "<=": value <= target, "=": value == target, ">": value > target, "<": value < target}[op]
        if not ok:
            return False, f"{element}{op}{target:g} mismatch ({value:g})"
    metal_count = sum(amount for element, amount in counts.items() if element in METALS)
    if not in_range(metal_count, parse_range(metals)):
        return False, f"metal count {metal_count:g} mismatch"
    return True, "ok"





