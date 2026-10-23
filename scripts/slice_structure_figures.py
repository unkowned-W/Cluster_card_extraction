"""Slice figure captions and nearby structural discussion from article Markdown."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAPTION = re.compile(r"^\s*(?:>\s*)?(?:Figure|Fig\.?|Plate)\s*((?:S)?\d+[A-Za-z]?)\s*[.:)]", re.IGNORECASE)
FIGURE_REF = re.compile(r"\b(?:figures?|figs?\.?|plates?)\s*((?:S)?\d+[A-Za-z]?)", re.IGNORECASE)
STRUCTURE = re.compile(r"\b(?:structure|structural|crystal|core|skeleton|framework|cage|shell|crown|wheel|ring|tube|cluster|building block|subunit|unit|polyhedr|bridg|vertex|edge|face|connect|link|assembl|coordination|topology|metal|lanthan|gadolinium|terbium|dysprosium|yttrium|oxo|hydroxo|nuclearity)\w*\b", re.IGNORECASE)
IMAGE = re.compile(r"^\s*!\[[^\]]*\]\([^)]*\)\s*$")

def split_paragraphs(text: str) -> list[dict]:
    paragraphs = []
    for match in re.finditer(r"\S[\s\S]*?(?=\n\s*\n|\Z)", text):
        content = match.group().strip()
        if not content or IMAGE.match(content):
            continue
        paragraphs.append({"start_line": text.count("\n", 0, match.start()) + 1,
                           "end_line": text.count("\n", 0, match.end()) + 1, "text": content})
    return paragraphs

def figure_numbers(text: str) -> set[str]:
    return {match.group(1).lower() for match in FIGURE_REF.finditer(text)}

def slice_document(path: Path, context_window: int = 5) -> dict:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    text = re.sub(r"(?m)^[ \t]*!\[[^\n]*\]\([^\n]*\)[ \t]*$", "", text)
    paragraphs = split_paragraphs(text)
    anchors = []
    for index, paragraph in enumerate(paragraphs):
        match = CAPTION.match(paragraph["text"])
        if match:
            anchors.append((index, match.group(1), paragraph))
    slices = []
    for caption_index, figure, _caption in anchors:
        start, end = max(0, caption_index-context_window), min(len(paragraphs), caption_index+context_window+1)
        selected = {caption_index}
        for index in range(start, end):
            if index == caption_index or CAPTION.match(paragraphs[index]["text"]):
                continue
            paragraph = paragraphs[index]["text"]
            if figure.lower() in figure_numbers(paragraph) or (abs(index-caption_index) <= 2 and STRUCTURE.search(paragraph)):
                selected.add(index)
        evidence = []
        for index in sorted(selected):
            paragraph = paragraphs[index]
            evidence.append({"role": "caption" if index == caption_index else "nearby_discussion",
                             "start_line": paragraph["start_line"], "end_line": paragraph["end_line"],
                             "text": paragraph["text"]})
        slices.append({"figure": figure, "evidence": evidence})
    return {"source_file": str(path), "source_format": "Markdown",
            "selection_method": "Figure captions plus structure-related or same-figure paragraphs within a bounded paragraph window; no semantic verification.",
            "context_window_paragraphs": context_window, "slices": slices}

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT/"documents"/"md", help="Markdown file or directory")
    parser.add_argument("--output", type=Path, default=ROOT/"data"/"structure_figure_slices", help="JSON output directory")
    parser.add_argument("--context-window", type=int, default=5, help="Paragraphs inspected before/after captions")
    args = parser.parse_args()
    if args.context_window < 0:
        parser.error("--context-window must be nonnegative")
    sources = [args.input] if args.input.is_file() else sorted(args.input.glob("*.md"))
    args.output.mkdir(parents=True, exist_ok=True)
    for source in sources:
        result = slice_document(source, args.context_window)
        destination = args.output/f"{source.stem}.json"
        destination.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        print(f"{source.name}: {len(result['slices'])} figure slices -> {destination}")

if __name__ == "__main__":
    main()
