import pandas as pd

import screening.cache as cache
import screening.core as core
from tests.test_core_rs import _prices


def test_screen_build_sector_rankings_scores_leadership_by_top_returns():
    ranked = pd.DataFrame(
        [
            {"ticker": "AAA", "return_n": 0.30, "rs": 0.20, "rs_weighted": 1.5},
            {"ticker": "BBB", "return_n": 0.20, "rs": 0.10, "rs_weighted": 1.4},
            {"ticker": "CCC", "return_n": 0.12, "rs": 0.02, "rs_weighted": 1.1},
            {"ticker": "DDD", "return_n": 0.04, "rs": -0.06, "rs_weighted": 0.9},
        ]
    )
    meta = pd.DataFrame(
        [
            {"ticker": "AAA", "sector": "Tech", "name_kr": "에이"},
            {"ticker": "BBB", "sector": "Tech", "name_kr": "비"},
            {"ticker": "CCC", "sector": "Energy", "name_kr": "씨"},
            {"ticker": "DDD", "sector": "Energy", "name_kr": "디"},
        ]
    )

    summary, members = core.screen_build_sector_rankings(
        ranked, meta, top_n_per_sector=2
    )

    assert list(summary["sector"]) == ["Tech", "Energy"]
    assert summary.loc[0, "sector_score"] == 0.25
    assert summary.loc[0, "top_ticker"] == "AAA"
    assert summary.loc[0, "top_name"] == "에이"
    assert list(members[members["sector"] == "Tech"]["ticker"]) == ["AAA", "BBB"]
    assert list(members[members["sector"] == "Tech"]["rank_in_sector"]) == [1, 2]


def test_screen_build_sector_rankings_handles_missing_sector_as_unknown():
    ranked = pd.DataFrame(
        [
            {"ticker": "AAA", "return_n": 0.10, "rs": 0.05},
            {"ticker": "BBB", "return_n": 0.03, "rs": -0.02},
        ]
    )
    meta = pd.DataFrame(
        [
            {"ticker": "AAA", "sector": ""},
            {"ticker": "BBB", "sector": None},
        ]
    )

    summary, members = core.screen_build_sector_rankings(ranked, meta)

    assert list(summary["sector"]) == ["미분류"]
    assert summary.loc[0, "stock_count"] == 2
    assert set(members["sector"]) == {"미분류"}


def test_screen_build_sector_rankings_can_filter_tiny_sectors():
    ranked = pd.DataFrame(
        [
            {"ticker": "AAA", "return_n": 0.30, "rs": 0.20},
            {"ticker": "BBB", "return_n": 0.20, "rs": 0.10},
            {"ticker": "CCC", "return_n": 0.50, "rs": 0.40},
        ]
    )
    meta = pd.DataFrame(
        [
            {"ticker": "AAA", "sector": "Tech"},
            {"ticker": "BBB", "sector": "Tech"},
            {"ticker": "CCC", "sector": "Solo"},
        ]
    )

    summary, members = core.screen_build_sector_rankings(
        ranked, meta, min_sector_size=2
    )

    assert list(summary["sector"]) == ["Tech"]
    assert set(members["sector"]) == {"Tech"}


def test_sector_rankings_work_from_full_cached_rs_pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "sector.db")
    cache.init_cache()
    for ticker, end, sector in (
        ("AAA", 150.0, "Tech"),
        ("BBB", 140.0, "Tech"),
        ("CCC", 120.0, "Energy"),
    ):
        cache.cache_save_prices(ticker, _prices(100.0, end))
        cache.cache_save_meta(
            ticker,
            {
                "name_en": ticker,
                "name_kr": ticker,
                "sector": sector,
                "market_cap": 1e9,
                "is_china": False,
                "is_risk": False,
            },
        )
    cache.cache_save_index("^TEST", _prices(100.0, 110.0))
    core.screen_rebuild_computed_snapshot(["AAA", "BBB", "CCC"])

    screen_df = core.screen_build_screening_df(["AAA", "BBB", "CCC"])
    ranked = core.screen_rank_rs(["AAA", "BBB", "CCC"], "^TEST", period=20, top_n=None)
    summary, members = core.screen_build_sector_rankings(ranked, screen_df)

    assert len(ranked) == 3
    assert list(summary["sector"]) == ["Tech", "Energy"]
    assert list(members[members["sector"] == "Tech"]["ticker"]) == ["AAA", "BBB"]
