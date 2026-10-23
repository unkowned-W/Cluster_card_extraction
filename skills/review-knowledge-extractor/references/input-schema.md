# Input JSON contract

Save a UTF-8 JSON object with exactly:

```json
{
  "doi": "10.xxxx/example",
  "title": "Review title",
  "md_file": "documents/md/10.xxxx_example.md",
  "cards": [
    {
      "category": "synthesis_strategy",
      "claim": "A standalone, review-supported knowledge point.",
      "explanation": "Why/when it holds and what examples in the review support it.",
      "scope": "Material family, system, or circumstances to which it applies.",
      "conditions": "Explicit relevant synthetic/measurement conditions, or null.",
      "caveats": "Exceptions, limits, uncertainty, or null.",
      "evidence_locations": ["Section 3.2; Table 1; refs. 12-15"],
      "basis": "review_synthesis"
    }
  ]
}
```

Categories: `synthesis_strategy`, `structural_pattern`, `structure_property_relationship`, `mechanistic_interpretation`, `method_comparison`, `limitation`, `other`. Use `other` sparingly. Basis is `review_synthesis` (the authors generalized over evidence) or `cited_example` (a useful but explicitly local observation). Prefer the former; a cited example must not be recast as a general conclusion.

`md_file` must resolve to an existing local Markdown file. Prefer a project-relative path. Evidence locations must be meaningful locators present in the reviewed Markdown, not copied quotations. Empty cards are permitted when the review yields no defensible knowledge points. The saver adds `card_id` and the source DOI/title/path to each saved card.
