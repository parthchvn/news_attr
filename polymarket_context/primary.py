"""Release-first Federal Reserve capture. Never backdate downloaded text.

Deduplicate information by source, release header and exact extracted text,
not volatile HTML. Preserve every response as a separately timed observation.
Legacy information.jsonl records are validated and retained unchanged.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

UTC = timezone.utc
MAX_BYTES = 3_000_000
SCHEMA = 'xvi.information.v1'
EXTRACTOR = 'fomc-paragraphs-v3'
TALLY = re.compile(r'The Federal Open Market Committee approved the following '
                   r'statement for release by a (\d+)\s*[-\u2013\u2014]\s*(\d+) vote:')


def clock() -> datetime:
    return datetime.now(UTC)


def stamp(value: str) -> datetime:
    t = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if t.tzinfo is None:
        raise ValueError('Timezone-aware timestamp required')
    return t.astimezone(UTC)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def allowed(url: str) -> str:
    u = urlsplit(url)
    if (u.scheme != 'https' or u.hostname != 'www.federalreserve.gov'
            or u.username or u.password or u.port not in (None, 443)):
        raise ValueError('Only HTTPS www.federalreserve.gov sources are supported')
    return url


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        allowed(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def request_bytes(url: str) -> tuple[bytes, dict]:
    req = Request(allowed(url), headers={'User-Agent': 'XVI-research-primary/1.1',
                                       'Accept-Encoding': 'identity'})
    with build_opener(SafeRedirect()).open(req, timeout=30) as r:
        data = r.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError('Response exceeds capture limit')
        return data, {'status': r.status, 'final_url': allowed(r.url),
                      'content_type': r.headers.get('Content-Type', '')}


class Paragraphs(HTMLParser):
    """Keep the v2 transform unchanged, including optional paragraph end tags."""
    P_END = frozenset({'address', 'article', 'aside', 'blockquote', 'details',
                      'div', 'dl', 'fieldset', 'figcaption', 'figure', 'footer',
                      'form', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'header',
                      'hgroup', 'hr', 'main', 'menu', 'nav', 'ol', 'p', 'pre',
                      'search', 'section', 'table', 'ul'})

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items, self.current, self.active = [], [], False

    def finish(self):
        if self.active:
            self.items.append(' '.join(''.join(self.current).split()))
        self.current, self.active = [], False

    def handle_starttag(self, tag, attrs):
        if tag in self.P_END:
            self.finish()
        if tag == 'p':
            self.active = True
        elif self.active and tag == 'br':
            self.current.append(' ')

    def handle_data(self, data):
        if self.active:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag in self.P_END or tag in {'body', 'html'}:
            self.finish()

    def close(self):
        super().close()
        self.finish()


def statement_text(raw: bytes, extractor: str = EXTRACTOR) -> tuple[str, str]:
    """Support named-voter and June/July 2026 vote-tally formats.

    v2 remains selectable for validating stored legacy records. A new tally
    format requires a release header, tally, policy-decision text and an
    explicit statement-end boundary; unknown/truncated formats fail closed.
    """
    if extractor not in {'fomc-paragraphs-v1', 'fomc-paragraphs-v2', EXTRACTOR}:
        raise ValueError('Unsupported extractor version: ' + str(extractor))
    parser = Paragraphs()
    parser.feed(raw.decode('utf-8-sig'))
    parser.close()
    start = next((i for i, p in enumerate(parser.items)
                  if re.match(r'For release at ', p)), None)
    if start is None:
        raise ValueError('No release header; layout is unsupported, not silently accepted')
    selected, boundary = [], False
    for p in parser.items[start + 1:]:
        if p.startswith(('For media inquiries', 'Implementation Note', 'Last Update:')):
            boundary = True
            break
        if p:
            selected.append(p)
    # The original named-voter extraction is deliberately byte-for-byte stable.
    if any(p.startswith('Voting for the monetary policy action') for p in selected):
        end = max(i for i, p in enumerate(selected) if p.startswith(('Voting for', 'Voting against')))
        return '\n\n'.join(selected[:end + 1]), parser.items[start]
    tally = TALLY.fullmatch(selected[0]) if selected else None
    if extractor == EXTRACTOR and tally:
        if (not boundary or len(selected) < 4 or int(tally.group(1)) < 1
                or not any(p.startswith('The Committee decided to ') and
                           'target range for the federal funds rate' in p for p in selected[1:])):
            raise ValueError('Incomplete vote-tally FOMC statement; not accepted')
        return '\n\n'.join(selected), parser.items[start]
    raise ValueError('Missing FOMC voting paragraph or supported vote tally; not a supported statement')


def feed_urls(raw: bytes) -> list[str]:
    root = ET.fromstring(raw)
    result = []
    for item in root.findall('.//item'):
        if (item.findtext('title') or '').strip() == 'Federal Reserve issues FOMC statement':
            url = allowed((item.findtext('link') or '').strip())
            if re.search(r'/monetary\d{8}a\.htm$', url):
                result.append(url)
    return sorted(set(result))


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    result = []
    for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f'{path}, line {number}: malformed JSON; preserve the file') from exc
        if not isinstance(row, dict):
            raise ValueError(f'{path}, line {number}: expected object')
        result.append(row)
    return result


def append_json(path: Path, row: dict) -> None:
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')


def atomic_text(path: Path, text: str) -> None:
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(text, encoding='utf-8')
    temporary.replace(path)


def save_raw(output: Path, raw: bytes) -> str:
    digest = sha(raw)
    target = output / 'raw' / (digest + '.bin')
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open('xb') as f:
            f.write(raw)
    except FileExistsError:
        if sha(target.read_bytes()) != digest:
            raise ValueError('Stored raw snapshot hash mismatch')
    return str(target.relative_to(output))


def validate_record(row: dict, root: Path) -> None:
    if row.get('schema') != SCHEMA or row.get('availability_basis') != 'collector_observation':
        raise ValueError('Only collector-observed records enter this forward adapter')
    times = [stamp(row[k]) for k in ('plan_recorded_at', 'request_started_at',
                                    'received_at', 'features_ready_at', 'usable_at')]
    if times != sorted(times) or times[-1] != times[-2]:
        raise ValueError('Invalid capture/processing clock order')
    allowed(row['source_url'])
    if row['discovery_mode'] != 'source_schedule' or not row['verified_text'].strip():
        raise ValueError('Missing independently scheduled exact text')
    if row.get('historical_usable_at') is not None:
        raise ValueError('Forward records cannot carry historical availability')
    if sha(row['verified_text'].encode()) != row['text_sha256']:
        raise ValueError('Text hash mismatch')
    plans = read_jsonl(root / 'plans.jsonl')
    if not any(p['recorded_at'] == row['plan_recorded_at'] and
               p['plan_sha256'] == row['plan_sha256'] == sha(json.dumps(p['plan'], sort_keys=True).encode()) and
               p['plan'].get('selection_basis') == 'source_schedule' for p in plans):
        raise ValueError('Capture plan provenance mismatch')
    raw_path = (root / row['raw_path']).resolve()
    if not raw_path.is_relative_to(root.resolve()):
        raise ValueError('Snapshot outside capture root')
    raw = raw_path.read_bytes()
    text, header = statement_text(raw, row.get('extractor', 'fomc-paragraphs-v2'))
    if sha(raw) != row['raw_sha256'] or text != row['verified_text']:
        raise ValueError('Source snapshot/extracted text mismatch')
    if header != row['source_release_claim']:
        raise ValueError('Release-header mismatch')
    match = re.search(r'/monetary(\d{8})a\.htm$', row['source_url'])
    if not match or row['information_event_id'] != 'fomc-' + match.group(1):
        raise ValueError('Information event/source identity mismatch')
    if row.get('content_version_id') and row['content_version_id'] != content_key(row):
        raise ValueError('Content version identity mismatch')


def eligible_at(row: dict, cutoff: str, root: Path) -> bool:
    validate_record(row, root)
    return stamp(row['usable_at']) < stamp(cutoff)


def content_key(row: dict) -> str:
    """A content identity is not an arrival or an independent information event."""
    values = [row['source_url'], row['source_release_claim'], row['text_sha256']]
    return sha(json.dumps(values, ensure_ascii=False, separators=(',', ':')).encode())


def canonical_records(rows: list[dict]) -> tuple[dict[str, dict], list[dict]]:
    """Call only with validated records. Never mutate/rewrite the input log."""
    unique, aliases = {}, []
    for row in sorted(rows, key=lambda r: (stamp(r['usable_at']), r['document_id'])):
        key = content_key(row)
        first = unique.setdefault(key, row)
        aliases.append({'document_id': row['document_id'], 'content_version_id': key,
                        'canonical_document_id': first['document_id'],
                        'record_usable_at': row['usable_at'],
                        'canonical_usable_at': first['usable_at']})
    return unique, aliases


def write_index(root: Path, rows: list[dict]) -> dict:
    unique, aliases = canonical_records(rows)
    for name, records in [('information_unique.jsonl', list(unique.values())),
                          ('version_aliases.jsonl', aliases)]:
        atomic_text(root / name, ''.join(json.dumps(r, ensure_ascii=False, allow_nan=False) + '\n'
                                        for r in records))
    return {'documents': len(unique), 'information_records': len(rows),
            'duplicate_information_records': len(rows) - len(unique),
            'distinct_information_events': len({r['information_event_id'] for r in rows})}


def capture(plan: dict, output: Path, fetcher=request_bytes) -> dict:
    """One single-writer cycle. Preserve errors, responses and old availability.

    Legacy duplicates remain in information.jsonl. Derived unique records keep
    their original earliest accepted IDs/times. Every new response, including
    unchanged content and parse errors, is recorded in observations.jsonl.
    A parse failure is never fixed by assigning an old HTML mtime to the text.
    """
    if plan.get('selection_basis') != 'source_schedule':
        raise ValueError('Plan must be independent of price movements')
    output.mkdir(parents=True, exist_ok=True)
    started = clock().isoformat()
    fingerprint = sha(json.dumps(plan, sort_keys=True).encode())
    append_json(output / 'plans.jsonl', {'plan_sha256': fingerprint, 'recorded_at': started, 'plan': plan})
    urls = [allowed(u) for u in plan.get('release_urls', [])]
    run = {'run_id': uuid.uuid4().hex, 'started_at': started, 'plan_sha256': fingerprint,
           'collector_version': 'primary-v3', 'records_added': 0,
           'unchanged_documents': 0, 'errors': [], 'continuous_coverage_certified': False}
    if plan.get('feed_url'):
        requested = clock().isoformat()
        try:
            raw, response = fetcher(allowed(plan['feed_url']))
            received = clock().isoformat()
            feed_path = save_raw(output, raw)
            run['feed_capture'] = {'raw_path': feed_path, 'raw_sha256': sha(raw),
                                   'request_started_at': requested, 'received_at': received, **response}
            urls += feed_urls(raw)
        except Exception as exc:
            run['errors'].append({'surface': plan['feed_url'], 'stage': 'feed',
                                  'request_started_at': requested, 'error': str(exc)})
    path = output / 'information.jsonl'
    rows = read_jsonl(path)
    for row in rows:
        validate_record(row, output)
    existing, _ = canonical_records(rows)
    run['selected_urls'] = sorted(set(urls))
    run['selected_statements'] = len(run['selected_urls'])
    for url in run['selected_urls']:
        observed = {'run_id': run['run_id'], 'source_url': url,
                    'plan_sha256': fingerprint, 'request_started_at': clock().isoformat(),
                    'stage': 'request'}
        try:
            if not re.search(r'/monetary\d{8}a\.htm$', url):
                raise ValueError('Only FOMC statement URLs supported')
            raw, response = fetcher(url)
            observed.update(received_at=clock().isoformat(), response=response, stage='parse')
            observed.update(raw_path=save_raw(output, raw), raw_sha256=sha(raw))
            text, header = statement_text(raw)
            ready = clock().isoformat()
            fields = {'source_url': url, 'source_release_claim': header, 'text_sha256': sha(text.encode())}
            key = content_key(fields)
            observed.update(content_version_id=key, features_ready_at=ready, stage='validate')
            if key not in existing:
                row = {'schema': SCHEMA, 'document_id': key, 'content_version_id': key,
                       **fields, 'information_event_id': 'fomc-' + re.search(r'monetary(\d{8})a', url).group(1),
                       'title': 'Federal Reserve issues FOMC statement',
                       'plan_sha256': fingerprint, 'plan_recorded_at': started,
                       'discovery_mode': 'source_schedule', 'request_started_at': observed['request_started_at'],
                       'received_at': observed['received_at'], 'features_ready_at': ready, 'usable_at': ready,
                       'availability_basis': 'collector_observation', 'historical_usable_at': None,
                       'raw_path': observed['raw_path'], 'raw_sha256': observed['raw_sha256'],
                       'verified_text': text, 'extractor': EXTRACTOR, 'response': response,
                       'market_ids': [], 'clock_assumption': 'Trusted collector UTC wall clock',
                       'note': 'Available after this capture/processing only. Not backdated to a release date.'}
                validate_record(row, output)
                append_json(path, row)
                rows.append(row)
                existing[key] = row
                run['records_added'] += 1
                observed['status'] = 'new_content'
            else:
                run['unchanged_documents'] += 1
                observed['status'] = 'known_content'
            observed['document_id'] = existing[key]['document_id']
            observed['canonical_usable_at'] = existing[key]['usable_at']
        except Exception as exc:
            observed.update(status='failed', error=str(exc))
            run['errors'].append({'surface': url, 'stage': observed['stage'],
                                  'request_started_at': observed['request_started_at'],
                                  'raw_path': observed.get('raw_path'), 'error': str(exc)})
        observed['completed_at'] = clock().isoformat()
        append_json(output / 'observations.jsonl', observed)
    run.update(write_index(output, rows))
    run.update(completed_at=clock().isoformat(), matched_trade_opportunities=0, empirical_delta_news=None,
               status=('partial_or_failed' if run['errors'] else
                       'complete' if run['selected_urls'] else 'no_matching_statements'))
    append_json(output / 'cycles.jsonl', run)
    atomic_text(output / 'status.json', json.dumps(run, indent=2))
    return run


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, default=Path('configs/primary_smoke.json'))
    p.add_argument('--output', type=Path, default=Path('runs/primary'))
    p.add_argument('--watch', action='store_true')
    p.add_argument('--interval-seconds', type=int, default=60)
    a = p.parse_args()
    if a.interval_seconds < 30:
        p.error('Use at least 30 seconds between cycles')
    plan = json.loads(a.plan.read_text())
    try:
        while True:
            result = capture(plan, a.output)
            print(json.dumps(result), flush=True)
            if not a.watch:
                raise SystemExit(0 if result['status'] == 'complete' else 1)
            time.sleep(a.interval_seconds)
    except KeyboardInterrupt:
        print('Collector stopped. No continued collection or gap-free coverage claimed.')


if __name__ == '__main__':
    main()
