# Structure-card schema guide

The machine-enforced schema is `output_schema.json`.

```text
article
├─ title, doi
└─ list_of_rare_earth_compounds[]
   ├─ identity: label, name, formula, CCDC numbers, refcodes
   ├─ material_class: cluster/complex, nuclearity, composition, elements
   ├─ synthesis
   │  ├─ main_text_has_explicit_synthesis
   │  ├─ si_used
   │  ├─ procedure and structured conditions
   │  └─ reagents with reported quantities
   ├─ properties
   │  ├─ reported
   │  ├─ property_type: none/magnetic/optical/both
   │  └─ measurements
   └─ source_locations[]
```

The property layer records existence and type before numerical data. Only magnetic and optical results are retained. Do not create a separate applications taxonomy; a genuinely demonstrated function such as magnetic refrigeration or luminescent sensing may be stated briefly in `summary`.

`needs_si` is deliberately absent from the card. It is workflow state derived by the validator and written only to `data/process_csv/si_required.csv`.

`source_locations` is a lightweight audit trail containing the supported field, source document, and section/table/figure location. It does not copy excerpts from the paper.

`structure_description` is an optional, concise author-grounded account of the metal-core shape, recurring building units, and how they connect. It complements rather than replaces `material_class.structural_family` or the separate CIF-derived cards. Record its evidence in `source_locations` and distinguish a proposed assembly scheme from an experimentally observed intermediate.
