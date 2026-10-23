#!/usr/bin/env python3
"""Search the enriched ledger without loading all source cards.

Similarity is transparent candidate ranking, not a crystallographic equivalence claim.
"""
import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def arr(value):
    try: return json.loads(value) if value else []
    except (ValueError, TypeError): return []


def has(value, query):
    return query.casefold() in (value or '').casefold()


def summary(row):
    names = ['compound_key','source_doi','compound_label','nuclearity','rare_earth_elements',
             'other_metal_elements','structural_family','structure_terms','reagent_names',
             'ligand_reagent_names','temperature','time','linked_structure_refcodes',
             'structure_availability','structure_gap_reason','local_card_path']
    arrays={'rare_earth_elements','other_metal_elements','structure_terms','reagent_names',
            'ligand_reagent_names','linked_structure_refcodes'}
    return {k: arr(row[k]) if k in arrays else row[k] for k in names}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--doi', help='Exact article DOI')
    p.add_argument('--compound-key', help='Exact DOI#compound[index]')
    p.add_argument('--ccdc', help='Exact article-reported or linked CCDC number')
    p.add_argument('--refcode', help='Exact article-reported or linked structure refcode')
    p.add_argument('--element', help='Exact rare-earth symbol, e.g. Gd')
    p.add_argument('--reagent', help='Substring in reagent name or formula; not necessarily ligand')
    p.add_argument('--ligand', help='Substring in role-tagged ligand reagent name only; can miss untagged ligands')
    p.add_argument('--family', help='Substring in article structural family')
    p.add_argument('--shape', help='Shape/motif term from family or article description')
    p.add_argument('--min-nuclearity', type=int)
    p.add_argument('--similar-to', help='Compound key (DOI#compound[index]) or exact refcode')
    p.add_argument('--limit', type=int, default=20)
    args = p.parse_args()
    if not any(v is not None for v in [args.doi,args.compound_key,args.ccdc,args.refcode,args.element,args.reagent,args.ligand,args.family,args.shape,args.min_nuclearity,args.similar_to]):
        p.error('Supply at least one query filter')
    if args.limit < 1: p.error('--limit must be positive')
    with (ROOT/'data'/'process_csv'/'project_card_ledger.csv').open(encoding='utf-8-sig',newline='') as f:
        compounds = [r for r in csv.DictReader(f) if r['record_type']=='compound_card']
    anchor = None
    if args.similar_to:
        candidates = [r for r in compounds if r['compound_key'].casefold()==args.similar_to.casefold() or
                      args.similar_to.casefold() in [x.casefold() for x in arr(r['linked_structure_refcodes'])]]
        if len(candidates)!=1:
            p.error(f'Anchor resolves to {len(candidates)} compounds; use an exact compound key (ambiguous refcodes are not accepted)')
        anchor=candidates[0]
    results=[]
    for r in compounds:
        if anchor and r['compound_key']==anchor['compound_key']: continue
        if args.doi and r['source_doi'].casefold()!=args.doi.casefold(): continue
        if args.compound_key and r['compound_key'].casefold()!=args.compound_key.casefold(): continue
        if args.ccdc and args.ccdc.casefold() not in [str(x).casefold() for x in arr(r['ccdc_number'])+arr(r['linked_structure_ccdc_numbers'])]: continue
        if args.refcode and args.refcode.casefold() not in [str(x).casefold() for x in arr(r['refcode'])+arr(r['linked_structure_refcodes'])]: continue
        if args.element and args.element.casefold() not in [x.casefold() for x in arr(r['rare_earth_elements'])]: continue
        if args.reagent and not any(has(x,args.reagent) for x in arr(r['reagent_names'])+arr(r['reagent_formulas'])): continue
        if args.ligand and not any(has(x,args.ligand) for x in arr(r['ligand_reagent_names'])): continue
        if args.family and not has(r['structural_family'],args.family): continue
        if args.shape and not any(has(x,args.shape) for x in arr(r['structure_terms'])): continue
        try: n=int(r['nuclearity'])
        except ValueError: n=None
        if args.min_nuclearity is not None and (n is None or n<args.min_nuclearity):continue
        item=summary(r)
        if anchor:
            shared_re=set(x.casefold() for x in arr(r['rare_earth_elements'])) & set(x.casefold() for x in arr(anchor['rare_earth_elements']))
            shared_other=set(x.casefold() for x in arr(r['other_metal_elements'])) & set(x.casefold() for x in arr(anchor['other_metal_elements']))
            shared_shape=set(x.casefold() for x in arr(r['structure_terms'])) & set(x.casefold() for x in arr(anchor['structure_terms']))
            shared_reagent=set(x.casefold() for x in arr(r['reagent_names'])) & set(x.casefold() for x in arr(anchor['reagent_names']))
            try: delta=abs(n-int(anchor['nuclearity'])) if n is not None else None
            except ValueError:delta=None
            same_family=bool(r['structural_family'] and r['structural_family'].casefold()==anchor['structural_family'].casefold())
            item['similarity_signals']={'same_source_doi':r['source_doi']==anchor['source_doi'],
                'same_structural_family':same_family,'shared_rare_earth_elements':sorted(shared_re),
                'shared_other_metal_elements':sorted(shared_other),'shared_shape_terms':sorted(shared_shape),
                'shared_reagent_names':sorted(shared_reagent),'nuclearity_difference':delta}
            item['_rank']=(int(same_family),int(r['source_doi']==anchor['source_doi']),len(shared_shape),int(delta==0),len(shared_other),len(shared_re),-delta if delta is not None else -100000)
        results.append(item)
    if anchor: results.sort(key=lambda x:x['_rank'],reverse=True)
    total=len(results)
    for x in results: x.pop('_rank',None)
    print(json.dumps({'total_matches':total,'shown':min(total,args.limit),
                      'anchor':summary(anchor) if anchor else None,'results':results[:args.limit],
                      'warning':'Similarity signals are index-level candidates; verify structural equivalence in source cards and CIF.' if anchor else
                                'Reagent search includes all roles; ligand search only finds explicit role tags.'},ensure_ascii=False,indent=2))

if __name__=='__main__':main()


