from screening import cache
from scripts.repair_us_metadata import repair_us_metadata


def test_repair_only_failed_response_rows(tmp_path, monkeypatch):
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    monkeypatch.setattr(cache, "DB_PATH", source)
    cache.init_cache()
    good = {"name_en": "Apple Inc.", "sector": "Technology", "country": "United States",
            "exchange": "NMS", "market_cap": 3e12, "is_risk": False, "is_china": False}
    for ticker in ("AAPL", "MSFT", "NVDA"):
        cache.cache_save_meta(ticker, good)
    monkeypatch.setattr(cache, "DB_PATH", target)
    cache.init_cache()
    cache.cache_save_meta("AAPL", {"name_en": "AAPL", "is_risk": True, "market_cap": 4e12})
    cache.cache_save_meta("MSFT", {**good, "name_en": "Microsoft", "market_cap": 5e12})
    cache.cache_save_meta("NVDA", {**good, "is_risk": True})
    assert repair_us_metadata(source) == 1
    assert cache.cache_load_meta("AAPL")["is_risk"] is False
    assert cache.cache_load_meta("AAPL")["market_cap"] == 4e12
    assert cache.cache_meta_age_days("AAPL") > 7
    assert cache.cache_load_meta("MSFT")["name_en"] == "Microsoft"
    assert cache.cache_load_meta("NVDA")["is_risk"] is True
    assert repair_us_metadata(source) == 0


def test_bad_source_cannot_clear_risk(tmp_path, monkeypatch):
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    for path in (source, target):
        monkeypatch.setattr(cache, "DB_PATH", path)
        cache.init_cache()
        cache.cache_save_meta("AAPL", {"name_en": "AAPL", "is_risk": True})
    assert repair_us_metadata(source) == 0
    assert cache.cache_load_meta("AAPL")["is_risk"] is True
