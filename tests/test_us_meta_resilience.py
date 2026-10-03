import pytest

from screening import batch, cache, data


@pytest.mark.parametrize("info", [{}, None, {"regularMarketPrice": 100}])
def test_empty_info_is_fetch_failure(monkeypatch, info):
    import yfinance
    monkeypatch.setattr(yfinance, "Ticker", lambda ticker: type("Ticker", (), {"info": info})())
    with pytest.raises(ValueError, match="metadata"):
        data.us_get_meta("AAPL")


def test_info_exception_propagates(monkeypatch):
    import yfinance
    def fail(ticker):
        raise RuntimeError("rate limited")
    monkeypatch.setattr(yfinance, "Ticker", fail)
    with pytest.raises(RuntimeError, match="rate limited"):
        data.us_get_meta("AAPL")


def test_confirmed_non_equity_still_excluded(monkeypatch):
    import yfinance
    info = {"quoteType": "ETF", "shortName": "Fund", "marketCap": 1e9,
            "regularMarketPrice": 100}
    monkeypatch.setattr(yfinance, "Ticker", lambda ticker: type("Ticker", (), {"info": info})())
    assert data.us_get_meta("FUND")["is_risk"] is True


def test_failed_fetch_preserves_cached_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "cache.db")
    cache.init_cache()
    original = {"name_en": "Apple Inc.", "sector": "Technology", "country": "United States",
                "market_cap": 3e12, "is_risk": False, "is_china": False}
    cache.cache_save_meta("AAPL", original)
    def fail(ticker):
        raise ValueError("metadata unavailable")
    monkeypatch.setattr(data, "us_get_meta", fail)
    assert batch._refresh_one_meta("AAPL", 7, True) == ("failed", "AAPL")
    assert cache.cache_load_meta("AAPL")["sector"] == "Technology"
    assert cache.cache_load_meta("AAPL")["is_risk"] is False


def test_corrupted_metadata_retries_inside_ttl(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "cache.db")
    cache.init_cache()
    cache.cache_save_meta("AAPL", {"name_en": "AAPL", "market_cap": 3e12,
                                   "is_risk": True, "is_china": False})
    monkeypatch.setattr(data, "us_get_meta", lambda ticker: {
        "name_en": "Apple Inc.", "sector": "Technology", "country": "United States",
        "market_cap": 3e12, "is_risk": False, "is_china": False})
    assert batch._refresh_one_meta("AAPL", 7, False) == ("updated", None)
    assert cache.cache_load_meta("AAPL")["is_risk"] is False
