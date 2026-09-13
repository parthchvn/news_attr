"""Release-first Federal Reserve capture. Never backdate today's text.

One cycle: python -m polymarket_context.primary --plan configs/primary_smoke.json
Watch: use configs/primary_forward.json --watch (requires a running host).
No trading, market-based discovery, model training or historical certification.
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
    req = Request(allowed(url), headers={'User-Agent': 'XVI-research-primary/1.0',
                                       'Accept-Encoding': 'identity'})
    with build_opener(SafeRedirect()).open(req, timeout=30) as r:
        data = r.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError('Response exceeds capture limit')
        return data, {'status': r.status, 'final_url': allowed(r.url),
                      'content_type': r.headers.get('Content-Type', '')}


class Paragraphs(HTMLParser):
    """Extract p text, honoring optional p end tags before block elements.

    The observed Fed releaseTime paragraph omits </p> before its share menu.
    Flush at that boundary rather than discarding the header or including
    navigation in its text. Inline elements retain their original spacing.
    """
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


def statement_text(raw: bytes) -> tuple[str, str]:
    parser = Paragraphs()
    parser.feed(raw.decode('utf-8-sig'))
    parser.close()
    start = next((i for i, p in enumerate(parser.items)
                  if re.match(r'For release at ', p)), None)
    if start is None:
        raise ValueError('No release header; layout is unsupported, not silently accepted')
    selected = []
    for p in parser.items[start + 1:]:
        if p.startswith(('For media inquiries', 'Implementation Note', 'Last Update:')):
            break
        if p:
            selected.append(p)
    if not selected or not any(p.startswith('Voting for the monetary policy action') for p in selected):
        raise ValueError('Missing FOMC voting paragraph; not a supported statement')
    # Stop at the last voting paragraph; never add footer/navigation as model text.
    end = max(i for i, p in enumerate(selected) if p.startswith(('Voting for', 'Voting against')))
    return '\n\n'.join(selected[:end + 1]), parser.items[start]


def feed_urls(raw: bytes) -> list[str]:
    root = ET.fromstring(raw)
    result = []
    for item in root.findall('.//item'):
        if (item.findtext('title') or '').strip() == 'Federal Reserve issues FOMC statement':
            url = allowed((item.findtext('link') or '').strip())
            if re.search(r'/monetary\d{8}a\.htm$', url):
                result.append(url)
    return sorted(set(result))


def append_json(path: Path, row: dict) -> None:
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')


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
    if sha(row['verified_text'].encode()) != row['text_sha256']:
        raise ValueError('Text hash mismatch')
    plans = [json.loads(line) for line in (root / 'plans.jsonl').read_text().splitlines()]
    if not any(p['recorded_at'] == row['plan_recorded_at'] and
               p['plan_sha256'] == row['plan_sha256'] == sha(json.dumps(p['plan'], sort_keys=True).encode()) and
               p['plan'].get('selection_basis') == 'source_schedule' for p in plans):
        raise ValueError('Capture plan provenance mismatch')
    raw_path = (root / row['raw_path']).resolve()
    if not raw_path.is_relative_to(root.resolve()):
        raise ValueError('Snapshot outside capture root')
    raw = raw_path.read_bytes()
    if sha(raw) != row['raw_sha256'] or statement_text(raw)[0] != row['verified_text']:
        raise ValueError('Source snapshot/extracted text mismatch')


def eligible_at(row: dict, cutoff: str, root: Path) -> bool:
    validate_record(row, root)
    return stamp(row['usable_at']) < stamp(cutoff)


def capture(plan: dict, output: Path, fetcher=request_bytes) -> dict:
    """One single-writer cycle. Fetch each selected version before any eligibility.

    HTTP/content failures are retained. A successful cycle is not continuous
    coverage; absence in a snapshot/feed is not evidence of no releases.
    """
    if plan.get('selection_basis') != 'source_schedule':
        raise ValueError('Plan must be independent of price movements')
    output.mkdir(parents=True, exist_ok=True)
    started = clock().isoformat()
    canonical = json.dumps(plan, sort_keys=True).encode()
    fingerprint = sha(canonical)
    append_json(output / 'plans.jsonl', {'plan_sha256': fingerprint, 'recorded_at': started, 'plan': plan})
    urls = [allowed(u) for u in plan.get('release_urls', [])]
    run = {'run_id': uuid.uuid4().hex, 'started_at': started, 'plan_sha256': fingerprint,
           'records_added': 0, 'errors': [], 'continuous_coverage_certified': False}
    if plan.get('feed_url'):
        try:
            raw, response = fetcher(allowed(plan['feed_url']))
            feed_path = save_raw(output, raw)
            run['feed_capture'] = {'raw_path': feed_path, 'received_at': clock().isoformat(), **response}
            urls += feed_urls(raw)
        except Exception as exc:
            run['errors'].append({'surface': 'feed', 'error': str(exc)})
    path = output / 'information.jsonl'
    existing = set()
    if path.exists():
        for line in path.read_text().splitlines():
            row = json.loads(line)
            validate_record(row, output)
            existing.add(row['document_id'])
    for url in sorted(set(urls)):
        requested = clock().isoformat()
        try:
            if not re.search(r'/monetary\d{8}a\.htm$', url):
                raise ValueError('Only FOMC statement URLs supported')
            raw, response = fetcher(url)
            received = clock().isoformat()
            raw_path = save_raw(output, raw)
            text, header = statement_text(raw)
            ready = clock().isoformat()
            identity = sha((url + '|' + sha(raw) + '|' + sha(text.encode())).encode())
            if identity not in existing:
                row = {'schema': SCHEMA, 'document_id': identity, 'source_url': url,
                       'information_event_id': 'fomc-' + re.search(r'monetary(\d{8})a', url).group(1),
                       'title': 'Federal Reserve issues FOMC statement',
                       'plan_sha256': fingerprint, 'plan_recorded_at': started,
                       'discovery_mode': 'source_schedule', 'request_started_at': requested,
                       'received_at': received, 'features_ready_at': ready, 'usable_at': ready,
                       'availability_basis': 'collector_observation',
                       'source_release_claim': header, 'historical_usable_at': None,
                       'raw_path': raw_path, 'raw_sha256': sha(raw),
                       'verified_text': text, 'text_sha256': sha(text.encode()),
                       'extractor': 'fomc-paragraphs-v2', 'response': response,
                       'market_ids': [], 'clock_assumption': 'Trusted collector UTC wall clock',
                       'note': 'Available only after this capture. Not backdated to the release date.'}
                validate_record(row, output)
                append_json(path, row)
                existing.add(identity)
                run['records_added'] += 1
        except Exception as exc:
            run['errors'].append({'surface': url, 'request_started_at': requested, 'error': str(exc)})
    run.update(completed_at=clock().isoformat(), documents=len(existing),
               status='partial_or_failed' if run['errors'] else 'complete',
               matched_trade_opportunities=0, empirical_delta_news=None)
    append_json(output / 'cycles.jsonl', run)
    (output / 'status.json').write_text(json.dumps(run, indent=2))
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
                raise SystemExit(1 if result['errors'] else 0)
            time.sleep(a.interval_seconds)
    except KeyboardInterrupt:
        print('Collector stopped. No continued collection or gap-free coverage claimed.')


if __name__ == '__main__':
    main()
