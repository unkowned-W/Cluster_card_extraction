"""Prepare SI-only context and safely merge synthesis patches into existing cards."""
from __future__ import annotations

import copy
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SKILL_ROOT = Path(__file__).resolve().parents[1]
PATCH_SCHEMA = SKILL_ROOT / "references" / "si_patch_schema.json"


def ledger_reason(doi: str, ledger: Path | None = None) -> str:
    path = ledger or ROOT / "data" / "process_csv" / "si_required.csv"
    if not path.exists():
        return ""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if (row.get("doi") or "").strip().lower() == doi.strip().lower():
                return row.get("reason") or ""
    return ""


def previous_log_reason(card_path: Path, logs_dir: Path) -> str:
    path = logs_dir / f"{card_path.stem}.codex.log"
    if not path.is_file():
        return "No previous extraction log available."
    # The original CLI log may contain the entire article; never pass that through.
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    diagnostics = [line.strip() for line in lines if line.startswith(("reason:", "needs_si:", "VALIDATOR RETURN CODE:"))]
    return "\n".join(diagnostics[-4:]) or "Previous log has no SI diagnostics; use the ledger and card."


def missing_fields(card: dict) -> list[dict]:
    result = []
    for index, compound in enumerate(card["list_of_rare_earth_compounds"]):
        synthesis = compound["synthesis"]
        if synthesis.get("main_text_has_explicit_synthesis"):
            continue
        reagents = synthesis.get("reagents") or []
        missing = []
        if not any(str(r.get("name") or "").strip() for r in reagents):
            missing.append("named reagents")
        if not any(re.search(r"\d", str(r.get("amount") or "")) for r in reagents):
            missing.append("reagent amounts")
        if not str(synthesis.get("procedure") or "").strip():
            missing.append("preparation procedure")
        # A ledger can also mark synthesis incomplete even when all three coarse checks pass.
        result.append({"compound_index": index, "label": compound.get("compound_label"), "formula": compound.get("formula"), "missing": missing or ["explicit synthesis evidence"]})
    return result


def make_si_prompt(row: dict[str, str], logs_dir: Path) -> str:
    card_path = Path(row["card_path"])
    card = json.loads(card_path.read_text(encoding="utf-8-sig"))
    si_paths = json.loads(row.get("si_paths") or "[]")
    missing = missing_fields(card)
    return f"""Use the SI-completion section of the local skill: {SKILL_ROOT / 'SKILL.md'}
Read only the supplied SI files, the existing card below, and these diagnostics. Do NOT open the main article Markdown/PDF, search the web, or re-extract the article.
DOI: {row['doi']}
SI files: {json.dumps(si_paths, ensure_ascii=False)}
Prior extraction log diagnostics (not the article text): {previous_log_reason(card_path, logs_dir)}
SI ledger reason: {ledger_reason(row['doi'])}
Missing synthesis by zero-based compound index: {json.dumps(missing, ensure_ascii=False)}
Existing card (context; do not repeat it in the output): {json.dumps(card, ensure_ascii=False)}

Return ONLY a JSON SI patch following the output schema. Include updates solely for indexed compounds with supported missing synthesis details. Each update contains only newly supported synthesis facts, with null for unknown scalar/array fields required by the patch schema, plus an SI section location. Never invent quantities or modify identity, main_text_has_explicit_synthesis, properties, or preexisting nonempty values. If SI lacks the answer, return an empty updates array. Do not modify project files.
"""


def merge_si_patch(card: dict, patch: dict) -> dict:
    result = copy.deepcopy(card)
    if patch.get("doi", "").strip().lower() != card["doi"].strip().lower():
        raise ValueError("SI patch DOI does not match existing card")
    compounds = result["list_of_rare_earth_compounds"]
    eligible = {entry["compound_index"] for entry in missing_fields(card)}
    seen = set()
    for update in patch.get("updates", []):
        index = update["compound_index"]
        if type(index) is not int or index not in eligible or index in seen:
            raise ValueError(f"Invalid or duplicate SI compound index: {index}")
        seen.add(index)
        synthesis = compounds[index]["synthesis"]
        additions = update.get("synthesis") or {}
        changed = False
        for key, value in additions.items():
            if key == "reagents":
                existing = synthesis.setdefault("reagents", [])
                for reagent in value or []:
                    name = (reagent.get("name") or "").strip().casefold()
                    matches = [r for r in existing if (r.get("name") or "").strip().casefold() == name]
                    if matches:
                        for field in ("formula", "role", "amount"):
                            if not matches[0].get(field) and reagent.get(field):
                                matches[0][field] = reagent[field]
                                changed = True
                    elif name:
                        existing.append(reagent)
                        changed = True
            elif key in {"procedure", "solvents", "temperature", "time", "ph", "vessel_or_method", "workup_and_crystallization", "yield"}:
                if not synthesis.get(key) and value:
                    synthesis[key] = value
                    changed = True
            else:
                raise ValueError(f"SI patch cannot modify {key}")
        if changed:
            # A solvent or yield alone is not evidence of the missing preparation.
            if additions.get("procedure") or additions.get("reagents"):
                synthesis["si_used"] = True
            location = update.get("si_location") or "SI synthesis section"
            entry = {"field": "synthesis", "source": "supporting_information", "location": location}
            if entry not in compounds[index]["source_locations"]:
                compounds[index]["source_locations"].append(entry)
    return result

