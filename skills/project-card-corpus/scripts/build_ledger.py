#!/usr/bin/env python3
"""Enrich the provenance ledger with searchable, compound-level card fields.

Reads the project card corpus and creates provenance plus compound-level rows.
Re-running rebuilds the index atomically without modifying source cards.
"""
import argparse
import csv
import json
import os
import re
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LEDGER = ROOT / 'data' / 'process_csv' / 'project_card_ledger.csv'
BASE = ['record_type','source_doi','review_doi','card_id','compound_label','nuclearity','ccdc_number','refcode','source_path','sample_path','match_basis','status','notes']
EXTRA = [
    'local_card_path','compound_index','compound_key','linked_compound_keys','match_cardinality',
    'structure_availability','structure_gap_reason',
    'title','formula','metal_composition','rare_earth_elements','other_metal_elements','all_metal_elements',
    'dimensionality','structural_family','structure_description','structure_terms',
    'reagent_names','reagent_formulas','ligand_reagent_names','ligand_basis','solvents','temperature','time','ph',
    'vessel_or_method','synthesis_procedure','workup_and_crystallization','yield',
    'synthesis_in_main_text','si_used','property_types','property_summary',
    'linked_structure_refcodes','linked_structure_ccdc_numbers','linked_structure_statuses',
    'crystal_system','space_group_hm','formula_moiety','atom_sites_available','bond_table_available',
    'metal_framework_topology','metal_framework_shape','geometry_basis','candidate_motif_status',
    'candidate_motif_nuclearity_basis','candidate_modules','candidate_module_compositions','interpretation_limit',
    'review_category','review_claim','review_scope','review_conditions','review_caveats','review_basis',
]
FIELDS = BASE + EXTRA
STRUCT_TERMS = ('wheel','ring','cage','barrel','tube','tubular','sphere','spherical','shell','core–shell',
                'core-shell','cube','cubane','disc','disk','triangle','tetrahedron','dumbbell','star-of-david',
                'nanocapsule','polyhedron','icosahedron','prism','keplerate','chain','framework')


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')) if value is not None else ''


def text(value):
    if value is None:
        return ''
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def unique(values):
    return list(dict.fromkeys(str(v) for v in values if v is not None and str(v).strip()))


def terms(value):
    s = (value or '').casefold()
    return [t for t in STRUCT_TERMS if re.search(r'(?<![a-z])' + re.escape(t) + r'(?![a-z])', s)]


def ligand_names(reagents):
    # This is a source role tag, not a chemical entity recognizer.
    selected = [r.get('name') for r in reagents if isinstance(r, dict) and
                'ligand' in str(r.get('role') or '').casefold()]
    return unique(selected)


def read_cards(dirname):
    for path in sorted((ROOT / 'data' / dirname).glob('*.json')):
        yield path, json.loads(path.read_text(encoding='utf-8'))


def local(path):
    return path.relative_to(ROOT).as_posix()


def key(doi, index):
    return f'{doi}#compound[{index}]'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--check', action='store_true', help='Validate relationships and print coverage without writing')
    args = ap.parse_args()
    preserved = []
    for kind, dirname in [('synthesis_card', 'extracted_cards'),
                          ('structure_card', 'cif_structure_cards'),
                          ('review_card', 'review_knowledge_cards')]:
        for path, card in read_cards(dirname):
            row = {k: '' for k in FIELDS}
            row.update(record_type=kind, local_card_path=local(path),
                       source_path=local(path), status='indexed')
            if kind == 'synthesis_card':
                row['source_doi'] = text(card.get('doi'))
            elif kind == 'structure_card':
                row['ccdc_number'] = text(card.get('ccdc_number'))
                row['refcode'] = text(card.get('refcode'))
                row['source_doi'] = text(card.get('doi'))
            else:
                row['card_id'] = path.stem
                row['review_doi'] = text(card.get('doi'))
            preserved.append(row)
    original_count = len(preserved)
    synth_cards = list(read_cards('extracted_cards'))
    synth_by_doi = {card['doi']: path for path, card in synth_cards}
    if len(synth_by_doi) != len(synth_cards):
        raise ValueError('Duplicate DOI across synthesis cards; compound keys would collide')
    structures = list(read_cards('cif_structure_cards'))
    by_ccdc, by_refcode = defaultdict(list), defaultdict(list)
    for path, card in structures:
        if card.get('ccdc_number'):
            by_ccdc[str(card['ccdc_number']).casefold()].append((path, card))
        if card.get('refcode'):
            by_refcode[str(card['refcode']).casefold()].append((path, card))
    compound_rows = []
    by_key = {}
    for path, card in synth_cards:
        for i, compound in enumerate(card.get('list_of_rare_earth_compounds') or []):
            material = compound.get('material_class') or {}
            synth = compound.get('synthesis') or {}
            reagents = [v for v in synth.get('reagents') or [] if isinstance(v, dict)]
            props = compound.get('properties') or {}
            cid = key(card['doi'], i)
            ccdc = unique(compound.get('ccdc_numbers') or [])
            refcodes = unique(compound.get('ccdc_refcodes') or [])
            matched = {}
            for x in ccdc:
                for sp, sc in by_ccdc.get(x.casefold(), []): matched[str(sc['refcode'])] = (sp, sc)
            for x in refcodes:
                for sp, sc in by_refcode.get(x.casefold(), []): matched[str(sc['refcode'])] = (sp, sc)
            re = unique(material.get('rare_earth_elements') or [])
            other = unique(material.get('other_metal_elements') or [])
            family = text(material.get('structural_family'))
            desc = text(compound.get('structure_description'))
            row = {k: '' for k in FIELDS}
            row.update(record_type='compound_card', source_doi=card['doi'], compound_label=text(compound.get('compound_label')),
                       nuclearity=text(material.get('nuclearity')), ccdc_number=compact(ccdc), refcode=compact(refcodes),
                       source_path='', sample_path=local(path), local_card_path=local(path),
                       match_basis='compound index in synthesis card', status='indexed',
                       structure_availability='matched_local_cif_card' if matched else 'no_corresponding_cif',
                       structure_gap_reason='' if matched else 'No corresponding CIF after project-level manual review; no exact local structure-card match.',
                       compound_index=str(i), compound_key=cid, title=text(card.get('title')),
                       formula=text(compound.get('formula')), metal_composition=text(material.get('metal_composition')),
                       rare_earth_elements=compact(re), other_metal_elements=compact(other),
                       all_metal_elements=compact(unique(re+other)), dimensionality=text(material.get('dimensionality')),
                       structural_family=family, structure_description=desc,
                       structure_terms=compact(unique(terms(family+' '+desc))),
                       reagent_names=compact(unique(r.get('name') for r in reagents)),
                       reagent_formulas=compact(unique(r.get('formula') for r in reagents)),
                       ligand_reagent_names=compact(ligand_names(reagents)),
                       ligand_basis='reagent role contains ligand; empty is not evidence of absence',
                       solvents=compact(unique(synth.get('solvents') or [])),
                       temperature=text(synth.get('temperature')), time=text(synth.get('time')),
                       ph=text(synth.get('ph')), vessel_or_method=text(synth.get('vessel_or_method')),
                       synthesis_procedure=text(synth.get('procedure')),
                       workup_and_crystallization=text(synth.get('workup_and_crystallization')),
                       **{'yield': text(synth.get('yield'))},
                       synthesis_in_main_text=text(synth.get('main_text_has_explicit_synthesis')),
                       si_used=text(synth.get('si_used')),
                       property_types=compact(unique([props.get('property_type')] +
                           [x.get('property_type') for x in props.get('measurements') or [] if isinstance(x, dict)])),
                       property_summary=text(props.get('summary')),
                       linked_structure_refcodes=compact(sorted(matched)),
                       linked_structure_ccdc_numbers=compact(unique(v[1].get('ccdc_number') for v in matched.values())),
                       linked_structure_statuses=compact(unique((v[1].get('candidate_structural_motifs') or {}).get('status') for v in matched.values())),
                       candidate_module_compositions=compact([m.get('metal_composition') for _,sc in matched.values()
                           for m in ((sc.get('candidate_structural_motifs') or {}).get('modules') or []) if isinstance(m,dict) and m.get('metal_composition')]))
            compound_rows.append(row)
            by_key[cid] = row

    # User-confirmed project-level manual review: unmatched compounds have no
    # corresponding CIF. This does not assert absence from the CCDC database.
    # Exact identifier-based links; DOI only limits same-article ambiguity and does not create a match.
    compounds_by_doi = defaultdict(list)
    for item in compound_rows: compounds_by_doi[item['source_doi']].append(item['compound_key'])
    reverse = defaultdict(set)
    for row in compound_rows:
        for ref in json.loads(row['linked_structure_refcodes']):
            reverse[ref.casefold()].add(row['compound_key'])
    for row in preserved:
        rt = row['record_type']
        if rt == 'synthesis_card':
            path = synth_by_doi.get(row['source_doi'])
            if path:
                row['local_card_path'] = local(path)
                row['linked_compound_keys'] = compact(compounds_by_doi[row['source_doi']])
        elif rt == 'structure_card':
            candidates = by_refcode.get(row['refcode'].casefold(), []) if row['refcode'] else by_ccdc.get(row['ccdc_number'].casefold(), [])
            if not candidates:
                continue  # Preserve classified missing-CIF rows.
            if len(candidates) != 1:
                row['notes'] = 'Duplicate structure identifier in local corpus; cannot select a unique card'
                continue
            path, card = candidates[0]
            row['local_card_path'] = local(path)
            row['structure_availability'] = 'matched_local_cif_card'
            links = sorted(reverse.get(str(card.get('refcode') or '').casefold(), []))
            row['linked_compound_keys'] = compact(links)
            row['match_cardinality'] = str(len(links))
            row['formula_moiety'] = text(card.get('formula_moiety'))
            row['crystal_system'] = text(card.get('crystal_system'))
            row['space_group_hm'] = text(card.get('space_group_hm'))
            row['atom_sites_available'] = text(card.get('atom_sites_available'))
            row['bond_table_available'] = text(card.get('bond_table_available'))
            framework = card.get('metal_framework') or {}
            row['metal_framework_topology'] = text(framework.get('topology'))
            row['metal_framework_shape'] = text(framework.get('approximate_shape'))
            row['geometry_basis'] = text(framework.get('geometry_basis'))
            motif = card.get('candidate_structural_motifs') or {}
            row['candidate_motif_status'] = text(motif.get('status'))
            row['candidate_motif_nuclearity_basis'] = text(motif.get('nuclearity_basis'))
            row['candidate_modules'] = compact(motif.get('modules')) if motif.get('modules') is not None else ''
            row['candidate_module_compositions'] = compact([m.get('metal_composition') for m in motif.get('modules') or []
                if isinstance(m,dict) and m.get('metal_composition')])
            row['interpretation_limit'] = text(card.get('interpretation_limit'))
            row['structure_terms'] = compact(unique(terms(text(card.get('description'))+' '+text(framework.get('approximate_shape')))))
            if len(links) == 1:
                src = by_key[links[0]]
                for field in ['compound_index','compound_key','formula','metal_composition','rare_earth_elements',
                              'other_metal_elements','all_metal_elements','structural_family','structure_description']:
                    row[field] = src[field]
            elif len(links) > 1:
                marker = 'Multiple compound candidates share exact identifier; no unique compound assignment'
                if marker not in row['notes']:
                    row['notes'] = (row['notes'] + '; ' if row['notes'] else '') + marker
        elif rt == 'review_card':
            path = ROOT / 'data' / 'review_knowledge_cards' / (row['card_id']+'.json')
            if not path.exists():
                continue
            c = json.loads(path.read_text(encoding='utf-8'))
            row['local_card_path'] = local(path)
            row['title'] = text(c.get('title'))
            for field, source in [('review_category','category'),('review_claim','claim'),('review_scope','scope'),
                                  ('review_conditions','conditions'),('review_caveats','caveats'),('review_basis','basis')]:
                row[field] = text(c.get(source))

    rows = preserved + compound_rows
    if len(by_key) != len(compound_rows):
        raise ValueError('Duplicate compound keys')
    summary = {'original_rows': original_count, 'compound_rows': len(compound_rows), 'total_rows': len(rows),
               'compounds_with_structure': sum(bool(json.loads(x['linked_structure_refcodes'])) for x in compound_rows),
               'no_corresponding_cif_after_manual_review': sum(x['structure_availability']=='no_corresponding_cif' for x in compound_rows),
               'compounds_with_role_tagged_ligand': sum(bool(json.loads(x['ligand_reagent_names'])) for x in compound_rows),
               'ambiguous_structure_rows': sum(x['record_type']=='structure_card' and int(x['match_cardinality'] or 0)>1 for x in preserved),
               'reported_ccdc_no_database_entry': sum(x['structure_availability']=='reported_ccdc_no_database_entry' for x in compound_rows),
               'no_corresponding_cif': sum(x['structure_availability']=='no_corresponding_cif' for x in compound_rows)}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.check:
        return
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.project_card_ledger.', suffix='.csv', dir=LEDGER.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS, lineterminator='\n')
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp, LEDGER)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


if __name__ == '__main__':
    main()



