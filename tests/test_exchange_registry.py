import pandas as pd
from polymarket_context.dc import participant_fills


def test_symbolic_contract_label_still_excludes_legacy_exchange():
    frame=pd.DataFrame({'contract':['NEGRISK_CTF_EXCHANGE']*2,
        'maker':['wallet-a','wallet-b'],
        'taker':['0xC5d563A36AE78145C45a50134d48A1215220f80a','smart-wallet']})
    selected,audit=participant_fills(frame)
    assert selected.taker.tolist()==['smart-wallet']
    assert audit['exchange_summary_rows_removed']==1


def test_symbolic_v2_contract_label_still_excludes_exchange():
    frame=pd.DataFrame({'contract':['CTF_EXCHANGE_V2'],
        'maker':['wallet-a'],'taker':['0xE111180000d2663C0091e4f400237545B87B996B']})
    selected,audit=participant_fills(frame)
    assert selected.empty and audit['exchange_summary_rows_removed']==1
