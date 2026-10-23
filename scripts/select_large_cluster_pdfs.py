"""List local papers whose extracted cards report metal nuclearity above 20."""

import csv
import json
from pathlib import Path

try:
    from .select_reextract_folder import merge_status, write_queue
except ImportError:  # Executed as a script.
    from select_reextract_folder import merge_status, write_queue


ROOT = Path(__file__).resolve().parents[1]
CARDS = ROOT / "data" / "extracted_cards"
PDFS = ROOT / "documents" / "pdf"
OUTPUT = ROOT / "data" / "process_csv" / "large_cluster_papers_gt20.csv"


def main():
    pdf_by_stem = {path.stem.casefold(): path for path in PDFS.glob("*.pdf")}
    rows = []
    missing_nuclearity = 0
    missing_pdf = []

    for card_path in sorted(CARDS.glob("*.json")):
        card = json.loads(card_path.read_text(encoding="utf-8"))
        pdf = pdf_by_stem.get(card_path.stem.casefold())
        if pdf is None:
            missing_pdf.append(card_path.name)
            continue

        qualifying = []
        for compound in card.get("list_of_rare_earth_compounds") or []:
            nuclearity = (compound.get("material_class") or {}).get("nuclearity")
            if nuclearity is None:
                missing_nuclearity += 1
            if isinstance(nuclearity, int) and not isinstance(nuclearity, bool) and nuclearity > 20:
                label = compound.get("compound_label") or compound.get("compound_name") or "unlabeled"
                qualifying.append((str(label), nuclearity))

        if qualifying:
            rows.append({
                "doi": card.get("doi", ""),
                "title": card.get("title", ""),
                "pdf_path": pdf.relative_to(ROOT).as_posix(),
                "card_path": card_path.relative_to(ROOT).as_posix(),
                "max_metal_nuclearity": max(nuclearity for _, nuclearity in qualifying),
                "qualifying_compound_count": len(qualifying),
                "qualifying_compounds": "; ".join(
                    f"{label} ({nuclearity})" for label, nuclearity in qualifying
                ),
            })

    rows.sort(key=lambda row: (-row["max_metal_nuclearity"], row["doi"]))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    rows = merge_status(rows, OUTPUT)
    if rows:
        write_queue(OUTPUT, rows)
    else:
        with OUTPUT.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=(
                "doi", "title", "pdf_path", "card_path", "max_metal_nuclearity",
                "qualifying_compound_count", "qualifying_compounds",
                "reextract_status", "reextract_updated_at",
            ))
            writer.writeheader()

    print(f"Selected {len(rows)} PDFs, {sum(row['qualifying_compound_count'] for row in rows)} compounds: {OUTPUT}")
    print(f"Compounds without nuclearity (matched PDF cards): {missing_nuclearity}")
    print(f"Cards without a matching PDF: {', '.join(missing_pdf) or 'none'}")


if __name__ == "__main__":
    main()
