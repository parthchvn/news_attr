"""Regressions for optional paragraph ends in the captured Fed HTML layout.

The text in this minimal fixture is synthetic, not a historical release.
"""
import json
import pytest
from polymarket_context.primary import Paragraphs, capture, statement_text, validate_record

HEADER = 'For release at 2:00 p.m. EDT'
VOTE = 'Voting for the monetary policy action were A and B.'


def test_release_header_before_share_menu_without_end_tag():
    raw = (f'<div><p class="article__time">May 07, 2025</p>'
           f'<h3>Federal Reserve issues FOMC statement</h3>'
           f'<p class="releaseTime">{HEADER}\n'
           '<ul><li><a>Share this page</a></li></ul></div>'
           '<div><p>SYNTHETIC policy text &amp; facts.</p>'
           f'<p>{VOTE}</p><p>For media inquiries, contact us.</p></div>').encode()
    text, header = statement_text(raw)
    assert header == HEADER
    assert text == 'SYNTHETIC policy text & facts.\n\n' + VOTE
    assert 'Share' not in text and 'May 07' not in text


def test_optional_ends_before_next_paragraph_and_end_of_file():
    text, header = statement_text(f'<p>{HEADER}<p>SYNTHETIC policy text.<p>{VOTE}'.encode())
    assert header == HEADER
    assert text == 'SYNTHETIC policy text.\n\n' + VOTE


def test_inline_elements_and_breaks_preserve_text():
    parser = Paragraphs()
    parser.feed('<p>Rate <strong>4</strong>-<em>1/4</em> &amp; <a href="#">facts</a><br>follow.</p>')
    parser.close()
    assert parser.items == ['Rate 4-1/4 & facts follow.']


def test_header_alone_still_fails_closed():
    with pytest.raises(ValueError, match='voting paragraph'):
        statement_text(f'<p>{HEADER}<ul><li>Share</li></ul><p>No votes.'.encode())


def test_optional_end_layout_capture_roundtrip(tmp_path):
    url = 'https://www.federalreserve.gov/newsevents/pressreleases/monetary20250507a.htm'
    raw = f'<p>{HEADER}<ul><li>Share</li></ul><p>SYNTHETIC statement.<p>{VOTE}'.encode()
    result = capture({'selection_basis':'source_schedule', 'release_urls':[url]},
                     tmp_path, lambda u:(raw, {'status':200, 'final_url':u}))
    assert result['errors'] == [] and result['records_added'] == 1
    record = json.loads((tmp_path/'information.jsonl').read_text())
    validate_record(record, tmp_path)
    assert record['extractor'] == 'fomc-paragraphs-v2'
    assert record['historical_usable_at'] is None
