import numpy as np
import pandas as pd
import sqlite3

import screening.cache as cache
import screening.batch as batch


def _ohlc(start: str, periods: int, first: float = 100.0) -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=periods)
    close = pd.Series(np.arange(first, first + periods), index=dates)
    return pd.DataFrame(
        {
            "Open": close - 0.5,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": 1_000.0,
        },
        index=dates,
    )


def test_index_chart_snapshot_keeps_110_and_drops_latest(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "chart.db")
    cache.init_cache()
    prices = _ohlc("2025-01-01", 120)

    saved = cache.cache_save_index_chart_snapshot("^TEST", prices, days=110)
    chart = cache.cache_load_index_chart_snapshot("^TEST")

    assert saved == 110
    assert len(chart) == 110
    assert chart.index[-1] == prices.index[-2]
    assert chart.index[-1] != prices.index[-1]
    assert list(chart.columns) == ["Open", "High", "Low", "Close"]


def test_index_chart_snapshot_returns_empty_for_legacy_db_without_table(
    tmp_path, monkeypatch
):
    db = tmp_path / "legacy.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE index_prices (index_code TEXT, date TEXT, close REAL)")
    monkeypatch.setattr(cache, "DB_PATH", db)

    chart = cache.cache_load_index_chart_snapshot("^TEST")

    assert chart.empty
    assert list(chart.columns) == ["Open", "High", "Low", "Close"]


def test_index_chart_snapshot_merges_next_refresh_before_dropping_latest(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "chart.db")
    cache.init_cache()
    initial = _ohlc("2025-01-01", 120)
    cache.cache_save_index_chart_snapshot("^TEST", initial, days=110)

    next_dates = pd.bdate_range(initial.index[-1], periods=3)
    next_prices = _ohlc(str(next_dates[0].date()), 3, first=500.0)
    cache.cache_save_index_chart_snapshot("^TEST", next_prices, days=110)
    chart = cache.cache_load_index_chart_snapshot("^TEST")

    assert len(chart) == 110
    assert chart.index[-1] == next_prices.index[-2]
    assert chart.index[-1] != next_prices.index[-1]


def test_index_refresh_builds_missing_chart_snapshot_even_when_close_is_current(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "chart.db")
    cache.init_cache()
    prices = _ohlc(str(pd.Timestamp.today().date()), 120)
    cache.cache_save_index("^TEST", prices)
    fetched: dict[str, int] = {}

    def _load_index(index_code: str, days: int) -> pd.DataFrame:
        fetched["days"] = days
        return prices

    monkeypatch.setattr(batch.us_data, "us_load_index", _load_index)
    monkeypatch.setattr(batch, "_days_since", lambda _: 0)

    result = batch.screen_refresh_index("^TEST", days=300, force=False)

    assert fetched["days"] == 300
    assert result["failed"] == []
    assert len(cache.cache_load_index_chart_snapshot("^TEST")) == 110
