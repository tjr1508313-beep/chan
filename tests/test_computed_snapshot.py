import numpy as np
import pandas as pd

import screening.cache as cache
import screening.core as core


def _prices(scale: float) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-01", periods=270)
    close = pd.Series(np.linspace(100.0, 200.0 * scale, len(dates)), index=dates)
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


def test_computed_snapshot_serves_screen_and_rank_without_raw_price_read(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "snapshot.db")
    cache.init_cache()
    for ticker, scale in (("AAA", 1.0), ("BBB", 1.2)):
        cache.cache_save_prices(ticker, _prices(scale))
        cache.cache_save_meta(
            ticker,
            {
                "name_en": ticker,
                "market_cap": 1e9,
                "is_china": False,
                "is_risk": False,
            },
        )
    cache.cache_save_index("^TEST", _prices(0.8))

    result = core.screen_rebuild_computed_snapshot(["AAA", "BBB"])
    assert result["metrics"] == 2
    assert result["returns"] == 112

    monkeypatch.setattr(
        core,
        "cache_load_prices_bulk",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("raw price read")),
    )
    screen_df = core.screen_build_screening_df(["AAA", "BBB"])
    ranked = core.screen_rank_rs(["AAA", "BBB"], "^TEST", period=20, top_n=2)

    assert list(screen_df.index) == ["AAA", "BBB"]
    assert list(ranked["ticker"]) == ["BBB", "AAA"]
