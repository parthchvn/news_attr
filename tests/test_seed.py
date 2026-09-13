from polymarket_context.seed import match_seed
from polymarket_context.dc import NewsIndex
import pandas as pd

M={'market_id':'m','question':'Inter Champions League?','outcome1_label':'Yes','required_term_groups':[['Inter'],['Champions League']]}
E={'episode_id':'e','market_id':'m','window_start':'2025-05-31T19:00:00Z','window_end':'2025-05-31T19:30:00Z','score':5}
D={'document_id':'d','url':'https://example.invalid/a','title':'Inter Champions League','snippet':'Inter Champions League report','published_at_claimed':None,'publication_date_claimed':'2025-05-31','candidate_episode_ids':['e'],'discovery_modes':['spike','manual_search']}


def test_date_only_no_cross_episode_matches():
    e2={**E,'episode_id':'other','window_start':'2024-01-01T12:00:00Z','window_end':'2024-01-01T13:00:00Z'}
    links=match_seed([E,e2],[D],{'markets':[M]})
    assert len(links)==1 and links[0]['temporal_role']=='date_only_timing_ambiguous'


def test_match_report_is_not_initial_catalyst():
    d={**D,'context_type':'retrospective_match_report'}
    assert match_seed([E],[d],{'markets':[M]})[0]['temporal_role']=='aftermath_report_not_pre_move_evidence'


def test_date_only_does_not_become_pre_trade_candidate():
    assert NewsIndex([D],M,False).at(pd.Timestamp('2025-06-01T20:00:00Z'),72,8)==[]
    assert NewsIndex([D],M,True).at(pd.Timestamp('2025-06-01T20:00:00Z'),72,8)==[]
