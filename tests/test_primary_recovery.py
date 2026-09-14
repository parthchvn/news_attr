"""Synthetic layout and repeat-poll regression tests, not empirical news results."""
from copy import deepcopy
from datetime import timedelta
import json
from urllib.error import URLError
import pytest
from polymarket_context.primary import (capture, statement_text, validate_record,
    read_jsonl, sha, append_json, eligible_at, stamp)
from polymarket_context.primary_audit import audit

URL = 'https://www.federalreserve.gov/newsevents/pressreleases/monetary20250507a.htm'
JUNE = 'https://www.federalreserve.gov/newsevents/pressreleases/monetary20260617a.htm'
PLAN = {'selection_basis': 'source_schedule', 'release_urls': [URL]}
OLD = (b'<p>For release at 2:00 p.m. EDT</p><p>SYNTHETIC economic content.</p>'
       b'<p>Voting for the monetary policy action were A and B.</p>'
       b'<p>For media inquiries, please contact the office.</p>')


def newer(vote='12 \u2013 0', dissent=False):
    s = ('<p>For release at 2:00 p.m. EDT<div>SHARE MENU</div>'
         '<p>The Federal Open Market Committee approved the following statement '
         f'for release by a {vote} vote:</p>'
         '<p>The Committee decided to maintain the target range for the federal funds rate at SYNTHETIC.</p>'
         '<p>SYNTHETIC economic activity.</p><p>SYNTHETIC inflation assessment.</p>')
    if dissent:
        s += '<p>Voting against the monetary policy action were C and D.</p>'
    return (s + '<p>For media inquiries, please contact the office.</p><p>FOOTER</p>').encode()


def fetch(raw):
    return lambda u: (raw, {'status': 200, 'final_url': u})


@pytest.mark.parametrize('vote', ['12 - 0', '12 \u2013 0', '12 \u2014 0'])
def test_tally_layout_without_named_supporters(vote):
    text, header = statement_text(newer(vote))
    assert 'SYNTHETIC inflation' in text and 'SHARE MENU' not in text
    assert 'media inquiries' not in text and 'FOOTER' not in text
    assert header == 'For release at 2:00 p.m. EDT'


def test_dissent_is_retained():
    text, _ = statement_text(newer('9 \u2013 3', True))
    assert text.endswith('Voting against the monetary policy action were C and D.')


def test_v2_is_still_rejected_on_new_layout():
    with pytest.raises(ValueError):
        statement_text(newer(), 'fomc-paragraphs-v2')


def test_truncated_tally_statement_fails_closed():
    raw = newer().split(b'<p>For media inquiries')[0]
    with pytest.raises(ValueError):
        statement_text(raw)


def test_tally_without_policy_decision_is_rejected():
    with pytest.raises(ValueError):
        statement_text(newer().replace(b'The Committee decided to', b'Random report'))


def test_named_layout_transform_is_unchanged():
    assert statement_text(OLD) == statement_text(OLD, 'fomc-paragraphs-v2')


def test_html_nonce_does_not_create_information(tmp_path):
    a = capture(PLAN, tmp_path, fetch(OLD + b'<!--nonce:first-->'))
    original = (tmp_path / 'information.jsonl').read_bytes()
    b = capture(PLAN, tmp_path, fetch(OLD + b'<!--nonce:second-->'))
    assert a['records_added'] == 1
    assert b['records_added'] == 0 and b['unchanged_documents'] == 1
    assert (tmp_path / 'information.jsonl').read_bytes() == original
    obs = read_jsonl(tmp_path / 'observations.jsonl')
    assert len(obs) == 2 and obs[0]['raw_sha256'] != obs[1]['raw_sha256']
    assert obs[0]['document_id'] == obs[1]['document_id']
    assert obs[0]['canonical_usable_at'] == obs[1]['canonical_usable_at']


def test_real_text_change_creates_version(tmp_path):
    capture(PLAN, tmp_path, fetch(OLD))
    result = capture(PLAN, tmp_path, fetch(OLD.replace(b'economic content', b'changed content')))
    assert result['records_added'] == 1 and result['documents'] == 2
    assert result['distinct_information_events'] == 1


def test_release_header_change_is_not_silently_deduplicated(tmp_path):
    capture(PLAN, tmp_path, fetch(OLD))
    result = capture(PLAN, tmp_path, fetch(OLD.replace(b'2:00', b'2:05')))
    assert result['records_added'] == 1


def test_same_text_different_release_is_not_merged(tmp_path):
    result = capture({**PLAN, 'release_urls': [URL, JUNE]}, tmp_path, fetch(OLD))
    assert result['documents'] == 2 and result['distinct_information_events'] == 2


def legacy_duplicates(root, count=3):
    """Simulate old raw-HTML identity; preserve valid old source/time records."""
    capture(PLAN, root, fetch(OLD))
    original = read_jsonl(root / 'information.jsonl')[0]
    (root / 'information.jsonl').write_text('')
    for i in range(count):
        r = deepcopy(original)
        raw = OLD + f'<!--old nonce {i}-->'.encode()
        digest = sha(raw)
        (root / 'raw' / (digest + '.bin')).write_bytes(raw)
        r.update(raw_sha256=digest, raw_path='raw/' + digest + '.bin', extractor='fomc-paragraphs-v2')
        r.pop('content_version_id')
        r['document_id'] = sha((URL + '|' + digest + '|' + r['text_sha256']).encode())
        for field in ('features_ready_at', 'usable_at'):
            r[field] = (stamp(original[field]) + timedelta(microseconds=i)).isoformat()
        validate_record(r, root)
        append_json(root / 'information.jsonl', r)
    return read_jsonl(root / 'information.jsonl')


def test_legacy_duplicates_preserved_but_unique_view_has_one(tmp_path):
    rows = legacy_duplicates(tmp_path, 103)
    original = (tmp_path / 'information.jsonl').read_bytes()
    report = audit(tmp_path)
    assert report['unique_content_versions'] == 1 and report['redundant_valid_records'] == 102
    assert (tmp_path / 'information.jsonl').read_bytes() == original
    unique = read_jsonl(tmp_path / 'information_unique.jsonl')
    assert unique == [rows[0]]
    assert not eligible_at(unique[0], unique[0]['usable_at'], tmp_path)
    assert len(read_jsonl(tmp_path / 'version_aliases.jsonl')) == 103


def test_resume_old_directory_does_not_duplicate_or_reset_time(tmp_path):
    rows = legacy_duplicates(tmp_path)
    result = capture(PLAN, tmp_path, fetch(OLD + b'<!--new nonce-->'))
    assert result['records_added'] == 0
    assert result['information_records'] == 3 and result['documents'] == 1
    assert read_jsonl(tmp_path / 'information_unique.jsonl')[0]['usable_at'] == rows[0]['usable_at']


def test_mixed_success_failure_retains_failed_url_and_raw(tmp_path):
    def partly(u):
        return (OLD if u == URL else b'<p>For release at 2:00 p.m. EDT</p><p>Unsupported.</p>', {'status': 200})
    result = capture({**PLAN, 'release_urls': [URL, JUNE]}, tmp_path, partly)
    assert result['status'] == 'partial_or_failed' and result['documents'] == 1
    assert result['errors'][0]['surface'] == JUNE and result['errors'][0]['stage'] == 'parse'
    assert (tmp_path / result['errors'][0]['raw_path']).exists()
    report = audit(tmp_path)
    assert report['validation_status'] == 'passed' and report['cycles_with_errors'] == 1


def test_dns_error_is_not_hidden(tmp_path):
    def offline(u):
        raise URLError('[Errno 8] nodename nor servname provided, or not known')
    result = capture(PLAN, tmp_path, offline)
    assert result['errors'][0]['stage'] == 'request' and result['documents'] == 0
    assert read_jsonl(tmp_path / 'observations.jsonl')[0]['status'] == 'failed'


def test_failed_attempt_then_new_parser_does_not_backdate(tmp_path):
    result = capture(PLAN, tmp_path, fetch(b'<p>Unsupported page</p>'))
    attempt = result['started_at']
    capture(PLAN, tmp_path, fetch(newer()))
    r = read_jsonl(tmp_path / 'information.jsonl')[0]
    assert r['historical_usable_at'] is None
    assert not eligible_at(r, attempt, tmp_path)


def test_no_matching_feed_is_explicit_not_success(tmp_path):
    feed = 'https://www.federalreserve.gov/feeds/press_monetary.xml'
    result = capture({'selection_basis': 'source_schedule', 'feed_url': feed},
                     tmp_path, fetch(b'<rss><channel></channel></rss>'))
    assert result['status'] == 'no_matching_statements' and result['documents'] == 0


def test_invalid_original_prevents_refreshing_unique_view(tmp_path):
    capture(PLAN, tmp_path, fetch(OLD))
    before = (tmp_path / 'information_unique.jsonl').read_bytes()
    r = read_jsonl(tmp_path / 'information.jsonl')[0]
    r['verified_text'] = 'tampered'
    (tmp_path / 'information.jsonl').write_text(json.dumps(r) + '\n')
    result = audit(tmp_path)
    assert result['validation_status'] == 'failed' and not result['unique_view_refreshed']
    assert (tmp_path / 'information_unique.jsonl').read_bytes() == before


def test_state_reappearance_is_preserved_in_observations(tmp_path):
    for raw in (OLD, OLD.replace(b'content', b'changed'), OLD):
        capture(PLAN, tmp_path, fetch(raw))
    assert len(read_jsonl(tmp_path / 'information.jsonl')) == 2
    obs = read_jsonl(tmp_path / 'observations.jsonl')
    assert len(obs) == 3 and obs[0]['document_id'] == obs[2]['document_id']
    assert obs[0]['document_id'] != obs[1]['document_id']
