import numpy as np
import pandas as pd

import screening.cache as cache
import screening.core as core


def _prices(start: float, end: float, periods: int = 270) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-01", periods=periods)
    close = pd.Series(np.linspace(start, end, periods), index=dates)
    return pd.DataFrame(
        {
            "Open": close,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": 1_000_000.0,
        },
        index=dates,
    )


def test_screen_calc_rs_does_not_reverse_ranking_when_index_return_is_negative():
    index_prices = _prices(100.0, 90.0, periods=21)
    stock_prices = pd.DataFrame(
        {
            "WINNER": np.linspace(100.0, 110.0, 21),
            "LOSER": np.linspace(100.0, 70.0, 21),
        },
        index=index_prices.index,
    )

    rs = core.screen_calc_rs(stock_prices, index_prices, period=20)

    assert rs["WINNER"] > 0.0
    assert rs["LOSER"] < 0.0
    assert rs["WINNER"] > rs["LOSER"]


def test_cached_rank_does_not_reverse_when_index_return_is_negative(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "negative-index.db")
    cache.init_cache()
    cache.cache_save_prices("WINNER", _prices(100.0, 110.0))
    cache.cache_save_prices("LOSER", _prices(100.0, 70.0))
    cache.cache_save_index("^TEST", _prices(100.0, 90.0))
    core.screen_rebuild_computed_snapshot(["WINNER", "LOSER"])

    ranked = core.screen_rank_rs(["WINNER", "LOSER"], "^TEST", period=20, top_n=2)

    assert list(ranked["ticker"]) == ["WINNER", "LOSER"]
    assert ranked["return_n"].is_monotonic_decreasing
    assert ranked.loc[0, "rs"] > 0.0
    assert ranked.loc[1, "rs"] < 0.0


def test_rs_ranking_always_matches_return_ranking():
    index_return = -0.2
    returns = pd.Series({"UP": 0.1, "FLAT": 0.0, "DOWN": -0.3})

    ranked = returns.map(
        lambda stock_return: core._relative_strength(stock_return, index_return)
    ).sort_values(ascending=False)

    assert list(ranked.index) == ["UP", "FLAT", "DOWN"]
