"""Rebuild local PDF/SI/MD/card/CIF reconciliation without altering source files."""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SECTION_START = "<!-- integrity-audit:start -->"
SECTION_END = "<!-- integrity-audit:end -->"


def stem(doi):
    return re.sub(r"[^A-Za-z0-9.\-]+", "_", doi.strip()).strip("._").lower()


def files(folder, suffixes):
    return {path.stem.lower(): path for path in (ROOT / folder).glob("*")
            if path.is_file() and path.suffix.lower() in suffixes and path.stat().st_size}


def paths(paths):
    return "|".join(sorted(str(path.relative_to(ROOT)).replace("\\", "/") for path in paths))


def si_doi_key(filename, doi_keys):
    prefix = re.split(r"_si(?:[_-]|$)", filename, maxsplit=1, flags=re.IGNORECASE)[0].lower()
    if prefix in doi_keys:
        return prefix
    publisher = re.match(r"^(anie\d{8,9}|cg\dc\d{5})", prefix)
    if publisher:
        token = publisher[1]
        suffix = ("anie." + token[4:]) if token.startswith("anie") else ("acs.cgd." + token[2:])
        matches = [key for doi, key in doi_keys.items() if doi.endswith(suffix)]
        if len(matches) == 1:
            return matches[0]
    return prefix


def write_csv(path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main(metadata_csv: Path | None = None):
    metadata_csv = metadata_csv or DATA / "structures.csv"
    if not metadata_csv.is_file():
        raise FileNotFoundError(f"Export metadata CSV first: {metadata_csv}")
    pdf = files("documents/pdf", {".pdf"})
    md = files("documents/md", {".md"})
    si = [path for path in (ROOT / "documents/si").glob("*")
          if path.is_file() and path.stat().st_size and path.suffix.lower() in {".pdf", ".docx", ".md", ".cif"}]
    si_md = [path for path in (ROOT / "documents/md").glob("*")
             if path.is_file() and path.stat().st_size and path.suffix.lower() == ".md"
             and re.search(r"_si(?:[_-]|$)", path.stem, re.IGNORECASE)]
    si_pending = [path for path in (DATA / "si_review_pending/si_md").glob("*.md") if path.stat().st_size]
    by_si = defaultdict(list)

    cifs_by_number, cifs_by_refcode = defaultdict(list), defaultdict(list)
    for path in (ROOT / "CIFs").glob("*.cif"):
        if not path.stat().st_size:
            continue
        match = re.fullmatch(r"(\d+)(?:_([a-zA-Z]{6}\d{0,2}))?", path.stem)
        if match:
            cifs_by_number[match[1]].append(path)
            if match[2]:
                cifs_by_refcode[match[2].upper()].append(path)

    catalog = defaultdict(list)
    with metadata_csv.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            catalog[row["doi"].lower()].append(row)
    # New runs use data/; existing corpora may still be kept under Cards/.
    article_cards_dir = DATA / "extracted_cards"
    if not article_cards_dir.is_dir():
        article_cards_dir = ROOT / "Cards" / "extracted_cards"
    structure_cards_dir = DATA / "cif_structure_cards"
    if not structure_cards_dir.is_dir():
        structure_cards_dir = ROOT / "Cards" / "cif_structure_cards"
    cards = {}
    for path in article_cards_dir.glob("*.json"):
        try:
            card = json.loads(path.read_text(encoding="utf-8-sig"))
            doi = card["doi"].strip().lower()
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if doi in cards:
            raise ValueError(f"duplicate DOI card: {doi}: {cards[doi][0]} and {path}")
        cards[doi] = (path, card)

    structure_cards_by_doi, structure_cards_by_number = defaultdict(set), defaultdict(set)
    for path in structure_cards_dir.glob("*.json"):
        try:
            structure = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        number = str(structure.get("ccdc_number") or "").strip()
        if number:
            structure_cards_by_number[number].add(path)
        for doi in structure.get("dois") or []:
            if isinstance(doi, str) and doi.strip():
                structure_cards_by_doi[doi.strip().lower()].add(path)

    required = {}
    si_required_path = DATA / "process_csv" / "si_required.csv"
    if si_required_path.is_file():
        with si_required_path.open(encoding="utf-8-sig", newline="") as handle:
            required = {row["doi"].strip().lower(): row for row in csv.DictReader(handle)}

    synthesis_gaps = defaultdict(list)
    for doi, (_, card) in cards.items():
        for index, compound in enumerate(card.get("list_of_rare_earth_compounds", []), 1):
            synthesis = compound.get("synthesis") or {}
            if synthesis.get("main_text_has_explicit_synthesis") or synthesis.get("si_used"):
                continue
            reagents = synthesis.get("reagents") or []
            missing = []
            if not any(str(item.get("name") or "").strip() for item in reagents if isinstance(item, dict)):
                missing.append("reagent names")
            if not any(re.search(r"\d", str(item.get("amount") or "")) for item in reagents if isinstance(item, dict)):
                missing.append("reagent amounts")
            if not str(synthesis.get("procedure") or "").strip():
                missing.append("procedure")
            if not missing:
                missing = ["synthesis provenance flag"]
            synthesis_gaps[doi].append({"doi": doi, "compound_index": index,
                                        "compound_label": compound.get("compound_label") or f"compound {index}",
                                        "missing": "; ".join(missing)})

    ledger, issues = [], []
    def issue(doi, kind, detail, compound="", ccdc="", refcode=""):
        issues.append({"doi": doi, "issue": kind, "compound": compound, "ccdc_number": ccdc,
                       "refcode": refcode, "detail": detail})

    all_dois = sorted(set(catalog) | set(cards))
    doi_keys = {doi: stem(doi) for doi in all_dois}
    for path in (*si, *si_md, *si_pending):
        by_si[si_doi_key(path.stem, doi_keys)].append(path)
    for doi in all_dois:
        key = stem(doi)
        paper_pdf = pdf.get(key)
        paper_md = md.get(key)
        paper_si = by_si.get(key, [])
        card_path, card = cards.get(doi, (None, {}))
        compounds = card.get("list_of_rare_earth_compounds") or []
        known = catalog.get(doi, [])
        by_number = defaultdict(set)
        for row in known:
            by_number[row["ccdc_number"].strip().removesuffix(".0")].add(row["refcode"].upper())
        card_numbers, card_refs, unnumbered, missing_cifs = set(), set(), 0, set()
        for index, compound in enumerate(compounds, 1):
            label = f"{index}: {compound.get('compound_label') or f'compound {index}'}"
            numbers = {str(number).strip().removesuffix(".0") for number in (compound.get("ccdc_numbers") or []) if str(number).strip()}
            refs = {str(ref).strip().upper() for ref in (compound.get("ccdc_refcodes") or []) if str(ref).strip()}
            card_refs.update(refs)
            if not numbers and not refs:
                unnumbered += 1
                issue(doi, "card_structure_without_ccdc", "card compound has no CCDC number or refcode; cannot link to CIF reliably", label)
            for number in numbers:
                card_numbers.add(number)
                if not cifs_by_number.get(number):
                    missing_cifs.add(number)
                    issue(doi, "card_ccdc_without_local_cif", "CCDC number recorded in card, no local CIF; CCDC availability not inferred", label, number)
                if number not in by_number:
                    issue(doi, "card_ccdc_not_in_catalog", "card number is absent from the selected structures catalog for this DOI", label, number)
            for ref in refs:
                if ref not in {code for number in numbers for code in by_number.get(number, set())}:
                    issue(doi, "card_refcode_unverified", "refcode not paired with card CCDC number in catalog", label, "|".join(sorted(numbers)), ref)
        extra = sorted(number for number, refs in by_number.items()
                       if number not in card_numbers and not refs.intersection(card_refs))
        structure_paths = structure_cards_by_doi.get(doi, set()) | {
            path for number in card_numbers for path in structure_cards_by_number.get(number, set())}
        missing_structure_cards = sorted(number for number in card_numbers
                                         if cifs_by_number.get(number) and not structure_cards_by_number.get(number))
        for number in missing_structure_cards:
            issue(doi, "local_cif_without_structure_card", "local CIF exists but no extracted CIF structure card", "", number)
        for number in extra:
            for ref in sorted(by_number[number]):
                issue(doi, "catalog_structure_not_in_card", "catalog contains DOI-linked structure not represented by a card CCDC number", "", number, ref)
        for number in by_number:
            if not cifs_by_number.get(number):
                issue(doi, "catalog_ccdc_without_local_cif", "catalog CCDC number has no local CIF", "", number,
                      "|".join(sorted(by_number[number])))
        if not paper_pdf:
            issue(doi, "missing_pdf", "no same-DOI local article PDF")
        if not paper_md:
            issue(doi, "missing_md", "no same-DOI nonempty main-text Markdown")
        if not card_path:
            issue(doi, "missing_card", "no local DOI paper card")
        ledger.append({"doi": doi, "pdf": paths([paper_pdf]) if paper_pdf else "",
                       "si": paths(paper_si), "md": paths([paper_md]) if paper_md else "",
                       "card": paths([card_path]) if card_path else "",
                       "cif_structure_cards": paths(structure_paths),
                       "structure_cards": len(structure_paths),
                       "card_ccdc_without_structure_card": "|".join(missing_structure_cards),
                       "cif_files": paths({path for number in set(by_number) | card_numbers
                                           for path in cifs_by_number.get(number, [])} |
                                          {path for ref in card_refs for path in cifs_by_refcode.get(ref, [])}),
                       "compounds": len(compounds), "card_structures_without_ccdc": unnumbered,
                       "card_ccdc_without_cif": "|".join(sorted(missing_cifs)),
                       "catalog_structures_not_in_card": "|".join(extra),
                       "catalog_structures": len(known),
                       "catalog_cifs": sum(bool(cifs_by_number.get(number)) for number in by_number),
                       "synthesis_gaps": len(synthesis_gaps.get(doi, [])),
                       "legacy_si_required": "pending" if doi in required else ""})

    card_stems = {stem(doi) for doi in cards}
    for collection, kind in ((pdf, "pdf_without_card"), (md, "md_without_card")):
        for filename, path in collection.items():
            if kind == "md_without_card" and re.search(r"_si(?:[_-]|$)", filename):
                continue
            if filename not in card_stems:
                issue("", kind, str(path.relative_to(ROOT)))
    for si_stem, si_paths in by_si.items():
        if si_stem not in card_stems:
            issue("", "si_without_card", paths(si_paths))
    catalog_numbers = {row["ccdc_number"].strip().removesuffix(".0") for rows in catalog.values() for row in rows}
    card_numbers_global = {str(number).strip().removesuffix(".0") for _, card in cards.values()
                           for compound in card.get("list_of_rare_earth_compounds", [])
                           for number in (compound.get("ccdc_numbers") or [])}
    for number, cif_paths in cifs_by_number.items():
        if number not in catalog_numbers:
            issue("", "cif_not_in_catalog", paths(cif_paths), "", number)
        if number not in card_numbers_global:
            issue("", "cif_without_card_reference", paths(cif_paths), "", number)
        for cif_path in cif_paths:
            text = cif_path.read_text(encoding="utf-8-sig", errors="replace")
            if not re.search(r"(?m)^_chemical_formula_(?:sum|moiety)\s+(?![.?](?:\s|$))\S", text, re.IGNORECASE):
                issue("", "cif_formula_unavailable", str(cif_path.relative_to(ROOT)), "", number)

    ledger_fields = ["doi", "pdf", "si", "md", "card", "cif_structure_cards", "structure_cards",
                     "card_ccdc_without_structure_card", "cif_files", "compounds",
                     "card_structures_without_ccdc", "card_ccdc_without_cif",
                     "catalog_structures_not_in_card", "catalog_structures", "catalog_cifs",
                     "synthesis_gaps", "legacy_si_required"]
    (DATA / "process_csv").mkdir(parents=True, exist_ok=True)
    write_csv(DATA / "final_integrity_ledger.csv", ledger, ledger_fields)
    write_csv(DATA / "final_integrity_issues.csv", issues, ["doi", "issue", "compound", "ccdc_number", "refcode", "detail"])
    write_csv(DATA / "final_synthesis_gaps.csv",
              [item for items in synthesis_gaps.values() for item in items],
              ["doi", "compound_index", "compound_label", "missing"])
    targets = sorted({(item["ccdc_number"], item["doi"]) for item in issues
                      if item["issue"] == "card_ccdc_without_local_cif"})
    write_csv(DATA / "process_csv" / "final_missing_cif_targets.csv",
              [{"ccdc_number": number, "doi": doi} for number, doi in targets], ["ccdc_number", "doi"])
    counts = Counter(item["issue"] for item in issues)
    review = DATA / "card_review.md"
    old = review.read_text(encoding="utf-8-sig") if review.is_file() else ""
    issues_by_doi = defaultdict(list)
    for item in issues:
        if item["doi"]:
            issues_by_doi[item["doi"]].append(item)
    ledger_by_doi = {row["doi"]: row for row in ledger}
    card_by_doi = {doi: card for doi, (_, card) in cards.items()}
    issue_labels = {
        "card_structure_without_ccdc": "card 化合物未记录 CCDC 编号或 refcode，无法可靠关联 CIF；也可能确实没有晶体沉积，需查论文/SI。",
        "card_ccdc_without_local_cif": "card 记录了 CCDC 编号，但项目本地没有对应 CIF；这不代表 CCDC 无记录。",
        "card_ccdc_not_in_catalog": "card 中的 CCDC 编号未出现在该 DOI 的 structures.csv 目录记录中，需核实编号及 DOI 归属。",
        "card_refcode_unverified": "card 中的 refcode 未与 structures.csv 中该 CCDC 编号配对，需核对。",
        "catalog_structure_not_in_card": "structures.csv 中存在该 DOI 关联结构，但 card 未列出该 CCDC/refcode；需判断是否漏提或属于其他化合物。",
        "catalog_ccdc_without_local_cif": "structures.csv 中有该 CCDC 编号，但本地缺少 CIF 文件。",
        "local_cif_without_structure_card": "本地有 CIF，但尚无对应的 CIF 结构 card。",
        "missing_pdf": "缺少同 DOI 的本地论文 PDF。",
        "missing_md": "缺少同 DOI 的非空正文 Markdown。",
        "missing_card": "缺少该 DOI 的论文 card。",
    }
    specific_review = [
        "### 按 card 列出的具体缺陷", "",
        "以下项目由本地文件和 structures.csv 自动比对生成，属于待人工核查线索，不等同于论文原文复核。CCDC/refcode 缺失可能是合理情况；本地缺 CIF 不能证明 CCDC 没有沉积。",
        "",
    ]
    review_dois = sorted(set(issues_by_doi) | set(synthesis_gaps))
    for doi in review_dois:
        row = ledger_by_doi[doi]
        card = card_by_doi.get(doi, {})
        title = str(card.get("title") or "无 card 标题").replace("|", "∣").replace("\n", " ").strip()
        card_path = row["card"] or "无本地 card"
        specific_review.extend([f"#### `{doi}` — {title}", "", f"Card：`{card_path}`。"])
        missing_sources = [name for name, value in (("论文 PDF", row["pdf"]), ("正文 Markdown", row["md"]), ("论文 card", row["card"])) if not value]
        if missing_sources:
            specific_review.append("缺少文件：" + "、".join(missing_sources) + "。")
        compound_details = defaultdict(list)
        article_details = []
        for item in issues_by_doi[doi]:
            label = issue_labels.get(item["issue"], item["detail"])
            if item["compound"]:
                identifiers = ", ".join(value for value in (item["ccdc_number"], item["refcode"]) if value)
                compound_details[item["compound"]].append(f"{identifiers + '：' if identifiers else ''}{label}")
            else:
                identifier = ", ".join(value for value in (item["ccdc_number"], item["refcode"]) if value)
                article_details.append(f"{identifier + '：' if identifier else ''}{label}")
        for gap in synthesis_gaps.get(doi, []):
            identity = f"{gap['compound_index']}: {gap['compound_label'] or '无标签'}"
            compound_details[identity].append("合成字段缺失：" + gap["missing"] + "。")
        for compound, defects in compound_details.items():
            compound_label = str(compound).replace("|", "∣").replace("\n", " ").strip()
            specific_review.append(f"- 化合物 {compound_label}：" + "；".join(dict.fromkeys(defects)))
        for defect in dict.fromkeys(article_details):
            specific_review.append(f"- 文献级/目录级问题：{defect}")
        if not compound_details and not article_details and not missing_sources:
            specific_review.append("- 当前自动核对未发现具体缺陷。")
        specific_review.append("")
    section = "\n".join([
        SECTION_START, "", f"## 当前完整性与 card 审阅（{date.today().isoformat()}）", "",
        "本节依据当前本地文件和 structures.csv 自动生成，不代表逐篇阅读论文/SI。每张有问题的 card 及其化合物级缺陷列在下方；字段明细见 `data/final_integrity_issues.csv` 与 `data/final_synthesis_gaps.csv`。",
        "完整 DOI 账目见 `data/final_integrity_ledger.csv`；CIF 补导出目标见 `data/process_csv/final_missing_cif_targets.csv`。", "",
        f"共 {len(ledger)} 个 DOI；card 编号无本地 CIF {counts['card_ccdc_without_local_cif']} 条；card 化合物无 CCDC/refcode {counts['card_structure_without_ccdc']} 条；目录结构未列入 card {counts['catalog_structure_not_in_card']} 条；缺论文 PDF/正文 MD/card {counts['missing_pdf']}/{counts['missing_md']}/{counts['missing_card']} 条。", "",
        "历史 `si_required.csv` 仅作流程工作台账；当前合成缺口以 card 实时核算的 `data/final_synthesis_gaps.csv` 为准。", "",
        *specific_review,
        "### 无法关联到 card 的本地文件", "",
        *[f"- CIF `{item['ccdc_number']}`：`{item['detail']}`" for item in issues if item["issue"] == "cif_without_card_reference"],
        *[f"- SI：`{item['detail']}`" for item in issues if item["issue"] == "si_without_card"], "",
        SECTION_END, "",
    ])
    if SECTION_START in old and SECTION_END in old:
        old = old[:old.index(SECTION_START)] + section + old[old.index(SECTION_END) + len(SECTION_END):].lstrip("\r\n")
    else:
        old = old.rstrip() + "\n\n" + section
    review.write_text(old, encoding="utf-8")
    print(f"DOIs={len(ledger)} issues={len(issues)} counts={dict(counts)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, default=DATA / "structures.csv")
    main(parser.parse_args().metadata)
