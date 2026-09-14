"""Validate a stopped primary capture and build a nondestructive unique view.

Usage: python -m polymarket_context.primary_audit --input runs/primary-forward
Reads original records, clocks and raw snapshots. Never edits them or reconstructs
missing historic availability. Audit only while the collector is stopped.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
from .primary import read_jsonl, validate_record, canonical_records, write_index, atomic_text, stamp


def audit(root: Path) -> dict:
    if not root.is_dir():
        raise FileNotFoundError(root)
    cycles = read_jsonl(root / 'cycles.jsonl')
    rows = read_jsonl(root / 'information.jsonl')
    invalid, valid = [], []
    for number, row in enumerate(rows, 1):
        try:
            validate_record(row, root)
            valid.append(row)
        except Exception as exc:
            invalid.append({'record': number, 'document_id': row.get('document_id'),
                            'error': f'{type(exc).__name__}: {exc}'})
    unique, aliases = canonical_records(valid)
    if not invalid:
        write_index(root, valid)
    errors = Counter((str(e.get('surface', 'unknown')), str(e.get('error', e)))
                     for c in cycles for e in c.get('errors', []))
    events = {}
    for row in valid:
        events.setdefault(row['information_event_id'], []).append(row)
    report = {
        'cycles_recorded': len(cycles),
        'cycles_with_errors': sum(bool(c.get('errors')) for c in cycles),
        'first_cycle_started_at': cycles[0].get('started_at') if cycles else None,
        'last_cycle_completed_at': cycles[-1].get('completed_at') if cycles else None,
        'latest_cycle_status': cycles[-1].get('status') if cycles else None,
        'latest_cycle_errors': cycles[-1].get('errors', []) if cycles else [],
        'document_version_records': len(rows), 'unique_content_versions': len(unique),
        'redundant_valid_records': len(valid) - len(unique),
        'distinct_information_events': len(events),
        'validation_status': 'failed' if invalid else 'passed' if valid else 'no_documents',
        'invalid_records': invalid,
        'unique_view_refreshed': not invalid,
        'errors_by_source': [{'source_url': u, 'error': e, 'count': n}
                             for (u, e), n in sorted(errors.items())],
        'events': [{'event_id': event_id, 'saved_records': len(rr),
                    'distinct_extracted_texts': len({r['text_sha256'] for r in rr}),
                    'first_usable_at': min(rr, key=lambda r: stamp(r['usable_at']))['usable_at'],
                    'source_urls': sorted({r['source_url'] for r in rr})}
                   for event_id, rr in sorted(events.items())],
        'note': ('Original records/raw snapshots/timestamps are unchanged. '
                 'Old cycle errors remain. Unique records retain earliest accepted availability. '
                 'Validation is not complete news coverage, market relevance, or a D-C dataset.')}
    atomic_text(root / 'audit.json', json.dumps(report, indent=2, ensure_ascii=False))
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, default=Path('runs/primary-forward'))
    a = p.parse_args()
    try:
        result = audit(a.input)
    except (OSError, ValueError, KeyError) as exc:
        p.exit(2, f'Audit stopped without altering original data: {exc}\n')
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result['validation_status'] != 'passed':
        p.exit(1)


if __name__ == '__main__':
    main()
