"""Select figure captions and nearby structural discussion from article Markdown."""
from __future__ import annotations

import re
from pathlib import Path


CAPTION = re.compile(r"^\s*(?:>\s*)?(?:Figure|Fig\.?)\s*\d+", re.IGNORECASE)
FIGURE_REFERENCE = re.compile(r"\b(?:fig(?:ure)?s?\.?\s*\d+|scheme\s*\d+)\b", re.IGNORECASE)
STRUCTURE = re.compile(
    r"\b(?:structure|structural|crystal|core|skeleton|framework|cage|shell|"
    r"wheel|ring|tube|cluster|building block|subunit|polyhedr|bridg|"
    r"vertex|edge|face|connect|link|assembl|coordination|topology)\w*\b",
    re.IGNORECASE,
)
GEOMETRY = re.compile(r"\b(?:distance|angle|diameter|dimension|geometry|\u00c5)\b", re.IGNORECASE)


def extract_context(path: Path, max_chars: int = 14000) -> str:
    """Return source-positioned candidates; never treat them as verified facts."""
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    text = re.sub(r"(?m)^[ \t]*!\[[^\n]*\]\([^\n]*\)[ \t]*$", "", text)
    paragraphs = []
    for match in re.finditer(r"\S[\s\S]*?(?=\n\s*\n|\Z)", text):
        paragraph = match.group().strip()
        if not paragraph or paragraph.startswith("![]("):
            continue
        line = text.count("\n", 0, match.start()) + 1
        paragraphs.append((line, paragraph))
    if not paragraphs:
        return ""

    scores = {}
    for index, (_, paragraph) in enumerate(paragraphs):
        if CAPTION.match(paragraph):
            scores[index] = 4 if STRUCTURE.search(paragraph) else 2
            for neighbor in range(max(0, index - 3), min(len(paragraphs), index + 3)):
                if neighbor != index and STRUCTURE.search(paragraphs[neighbor][1]):
                    scores[neighbor] = max(scores.get(neighbor, 0), 3)
        elif STRUCTURE.search(paragraph):
            score = 1 + bool(FIGURE_REFERENCE.search(paragraph)) * 2 + bool(GEOMETRY.search(paragraph))
            scores[index] = max(scores.get(index, 0), score)

    selected = set()
    used = 0
    for index in sorted(scores, key=lambda position: (-scores[position], position)):
        line, paragraph = paragraphs[index]
        chunk_size = min(len(paragraph), 3500) + 40
        if used + chunk_size > max_chars:
            continue
        selected.add(index)
        used += chunk_size
    return "\n\n".join(
        f"[Markdown line {line}] {paragraph[:3500]}"
        for index, (line, paragraph) in enumerate(paragraphs) if index in selected
    )
