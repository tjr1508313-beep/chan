import pandas as pd
import pytest

import screening.cache as cache
import screening.core as core
from tests.test_core_rs import _prices


def test_screen_build_sector_rankings_scores_leadership_by_top_rs():
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
        ranked, meta, top_n_per_sector=2, min_sector_size=1
    )

    assert list(summary["sector"]) == ["Tech", "Energy"]
    # 강도 = 상위 2종목 rs 평균 (0.20, 0.10) → 0.15
    assert summary.loc[0, "sector_score"] == pytest.approx(0.15)
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

    summary, members = core.screen_build_sector_rankings(
        ranked, meta, min_sector_size=1
    )

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
    summary, members = core.screen_build_sector_rankings(
        ranked, screen_df, min_sector_size=1
    )

    assert len(ranked) == 3
    assert list(summary["sector"]) == ["Tech", "Energy"]
    assert list(members[members["sector"] == "Tech"]["ticker"]) == ["AAA", "BBB"]


def test_sector_rankings_breadth_breaks_tie_on_equal_strength():
    # 두 섹터 강도(상위N rs 평균) 동일(0.05), 폭(rs>0 비율)만 다름 → 폭 큰 쪽이 위
    ranked = pd.DataFrame(
        [
            {"ticker": "A1", "return_n": 0.06, "rs": 0.06},
            {"ticker": "A2", "return_n": 0.04, "rs": 0.04},
            {"ticker": "A3", "return_n": 0.05, "rs": 0.05},   # Broad: rs 평균 0.05, 폭 3/3=1.0
            {"ticker": "B1", "return_n": 0.10, "rs": 0.10},
            {"ticker": "B2", "return_n": 0.10, "rs": 0.10},
            {"ticker": "B3", "return_n": -0.05, "rs": -0.05},  # Narrow: rs 평균 0.05, 폭 2/3
        ]
    )
    meta = pd.DataFrame(
        [
            {"ticker": "A1", "sector": "Broad"},
            {"ticker": "A2", "sector": "Broad"},
            {"ticker": "A3", "sector": "Broad"},
            {"ticker": "B1", "sector": "Narrow"},
            {"ticker": "B2", "sector": "Narrow"},
            {"ticker": "B3", "sector": "Narrow"},
        ]
    )

    summary, _ = core.screen_build_sector_rankings(ranked, meta, min_sector_size=3)

    assert summary.loc[0, "sector_score"] == pytest.approx(0.05)
    assert summary.loc[1, "sector_score"] == pytest.approx(0.05)
    assert list(summary["sector"]) == ["Broad", "Narrow"]


def test_sector_rankings_bear_market_puts_least_negative_on_top():
    # 전 섹터 하락(rs<0): 곱셈이라면 뒤집혔을 배치. 백분위 혼합은 덜 빠진 섹터를 위로.
    ranked = pd.DataFrame(
        [
            {"ticker": "X1", "return_n": -0.02, "rs": -0.02},
            {"ticker": "X2", "return_n": -0.03, "rs": -0.03},
            {"ticker": "X3", "return_n": -0.04, "rs": -0.04},  # Mild: rs 평균 -0.03
            {"ticker": "Y1", "return_n": -0.06, "rs": -0.06},
            {"ticker": "Y2", "return_n": -0.07, "rs": -0.07},
            {"ticker": "Y3", "return_n": -0.08, "rs": -0.08},  # Deep: rs 평균 -0.07
        ]
    )
    meta = pd.DataFrame(
        [
            {"ticker": "X1", "sector": "Mild"},
            {"ticker": "X2", "sector": "Mild"},
            {"ticker": "X3", "sector": "Mild"},
            {"ticker": "Y1", "sector": "Deep"},
            {"ticker": "Y2", "sector": "Deep"},
            {"ticker": "Y3", "sector": "Deep"},
        ]
    )

    summary, _ = core.screen_build_sector_rankings(ranked, meta, min_sector_size=3)

    assert list(summary["sector"]) == ["Mild", "Deep"]


def test_sector_rankings_default_min_size_excludes_two_stock_sector():
    ranked = pd.DataFrame(
        [
            {"ticker": "T1", "return_n": 0.10, "rs": 0.05},
            {"ticker": "T2", "return_n": 0.08, "rs": 0.03},
            {"ticker": "T3", "return_n": 0.06, "rs": 0.01},
            {"ticker": "P1", "return_n": 0.20, "rs": 0.15},
            {"ticker": "P2", "return_n": 0.18, "rs": 0.13},
        ]
    )
    meta = pd.DataFrame(
        [
            {"ticker": "T1", "sector": "Three"},
            {"ticker": "T2", "sector": "Three"},
            {"ticker": "T3", "sector": "Three"},
            {"ticker": "P1", "sector": "Two"},
            {"ticker": "P2", "sector": "Two"},
        ]
    )

    # min_sector_size 미지정 → 기본 3 → 2종목 섹터 제외
    summary, members = core.screen_build_sector_rankings(ranked, meta)

    assert list(summary["sector"]) == ["Three"]
    assert set(members["sector"]) == {"Three"}
