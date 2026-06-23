import pandas as pd

import scripts.show_sector_rs as cli


def _snapshot():
    summary = pd.DataFrame(
        [
            {
                "rank": 1,
                "sector": "Tech",
                "sector_score": 0.30,
                "positive_ratio": 1.0,
                "stock_count": 2,
                "top_ticker": "AAA",
                "top_name": "Alpha",
            },
            {
                "rank": 2,
                "sector": "Energy",
                "sector_score": 0.10,
                "positive_ratio": 0.5,
                "stock_count": 1,
                "top_ticker": "CCC",
                "top_name": "Charlie",
            },
        ]
    )
    members = pd.DataFrame(
        [
            {
                "sector": "Tech",
                "rank_in_sector": 1,
                "ticker": "AAA",
                "name_kr": "",
                "name_en": "Alpha",
                "return_n": 0.30,
                "rs": 0.25,
                "rs_weighted": 1.5,
            },
            {
                "sector": "Energy",
                "rank_in_sector": 1,
                "ticker": "CCC",
                "name_kr": "",
                "name_en": "Charlie",
                "return_n": 0.10,
                "rs": 0.05,
                "rs_weighted": 1.1,
            },
        ]
    )
    return {
        "index_code": "KS11",
        "period": 20,
        "filter_stats": {"total": 3, "final": 3},
        "lag_excluded": 0,
        "universe_source": "argument",
        "universe_count": 3,
        "input_count": 3,
        "ranked": pd.DataFrame({"ticker": ["AAA", "CCC"]}),
        "sector_summary": summary,
        "sector_members": members,
    }


def test_cli_sector_option_prints_only_requested_sector(monkeypatch, capsys):
    monkeypatch.setattr(cli, "screen_build_sector_snapshot", lambda *args, **kwargs: _snapshot())

    assert cli.main(["--index-code", "KS11", "--sector", "tech"]) == 0

    out = capsys.readouterr().out
    assert "Sector: tech" in out
    assert "AAA Alpha" in out
    assert "CCC Charlie" not in out
