"""Report mismatched CCDC identifiers between article cards and exported structures."""
import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ['doi','card_path','compound_index','compound_label','status','card_ccdc_numbers','card_refcodes','catalog_ccdc_numbers','catalog_refcodes']

def ids(values):
    return {str(v).strip().upper() for v in (values or []) if str(v).strip()}

def audit(catalog, cards_dir):
    by_doi = defaultdict(list)
    with catalog.open(encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            doi = (row.get('doi') or '').strip().lower()
            if doi:
                by_doi[doi].append(row)
    cards = {}
    for path in sorted(cards_dir.glob('*.json')):
        card = json.loads(path.read_text(encoding='utf-8-sig'))
        doi = str(card.get('doi') or '').strip().lower()
        if not doi or doi in cards:
            raise ValueError(f'Empty or duplicate card DOI: {path} ({doi})')
        cards[doi] = (path, card)
    output = []
    for doi in sorted(set(by_doi) | set(cards)):
        catalog_rows = by_doi.get(doi, [])
        numbers = ids(r.get('ccdc_number') for r in catalog_rows)
        refs = ids(r.get('refcode') for r in catalog_rows)
        path, card = cards.get(doi, (None, {}))
        seen_numbers, seen_refs = set(), set()
        for index, compound in enumerate(card.get('list_of_rare_earth_compounds') or [], 1):
            found_numbers = ids(compound.get('ccdc_numbers'))
            found_refs = ids(compound.get('ccdc_refcodes'))
            seen_numbers.update(found_numbers)
            seen_refs.update(found_refs)
            status = ('card_identifier_not_in_catalog' if (found_numbers - numbers or found_refs - refs) else
                      'compound_without_identifier' if not (found_numbers or found_refs) else 'matched')
            output.append(dict(doi=doi, card_path=str(path), compound_index=str(index),
                               compound_label=str(compound.get('compound_label') or ''), status=status,
                               card_ccdc_numbers='|'.join(sorted(found_numbers)), card_refcodes='|'.join(sorted(found_refs)),
                               catalog_ccdc_numbers='|'.join(sorted(numbers)), catalog_refcodes='|'.join(sorted(refs))))
        missing_numbers, missing_refs = numbers - seen_numbers, refs - seen_refs
        if missing_numbers or missing_refs or not path:
            output.append(dict(doi=doi, card_path=str(path or ''), compound_index='', compound_label='',
                               status='catalog_not_in_card' if path else 'missing_card',
                               card_ccdc_numbers='', card_refcodes='', catalog_ccdc_numbers='|'.join(sorted(missing_numbers)),
                               catalog_refcodes='|'.join(sorted(missing_refs))))
        if path and not catalog_rows:
            output.append(dict(doi=doi, card_path=str(path), compound_index='', compound_label='', status='card_doi_not_in_catalog',
                               card_ccdc_numbers='', card_refcodes='', catalog_ccdc_numbers='', catalog_refcodes=''))
    return output

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, default=ROOT/'data/structures.csv')
    parser.add_argument('--cards', type=Path, default=ROOT/'data/extracted_cards')
    parser.add_argument('--output', type=Path, default=ROOT/'data/process_csv/card_ccdc_audit.csv')
    parser.add_argument('--preview', action='store_true')
    args = parser.parse_args()
    rows = audit(args.catalog, args.cards)
    print('CCDC audit:', dict(Counter(r['status'] for r in rows)))
    if args.preview:
        for row in (r for r in rows if r['status'] != 'matched'):
            print(row['status'], row['doi'], row['compound_label'], row['catalog_ccdc_numbers'])
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        print('report:', args.output)

if __name__ == '__main__':
    main()
