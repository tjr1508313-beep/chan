import pytest
import screening.cache as cache


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    db = tmp_path / "test_cache.db"
    monkeypatch.setattr(cache, "DB_PATH", db)
    cache.init_cache()
    return db


def _seed_meta(ticker, **over):
    meta = {
        "name_en": ticker, "name_kr": ticker, "sector": None,
        "country": "South Korea", "exchange": "KOSPI",
        "market_cap": 1e12, "is_china": False, "is_risk": False,
    }
    meta.update(over)
    cache.cache_save_meta(ticker, meta)


def test_migration_adds_caution_flags_column(tmp_db):
    with cache._connect() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(metadata)")}
    assert "caution_flags" in cols


def test_update_risk_flags_sets_and_clears(tmp_db):
    _seed_meta("005930")
    _seed_meta("000660")
    cache.update_risk_flags({
        "005930": {"is_risk": True, "labels": ["관리"]},
        "000660": {"is_risk": False, "labels": ["투자경고"]},
    })
    m1 = cache.cache_load_meta("005930")
    m2 = cache.cache_load_meta("000660")
    assert m1["is_risk"] is True
    assert m1["caution_flags"] == "관리"
    assert m2["is_risk"] is False
    assert m2["caution_flags"] == "투자경고"

    cache.update_risk_flags({"005930": {"is_risk": True, "labels": ["관리"]}})
    m2b = cache.cache_load_meta("000660")
    assert m2b["is_risk"] is False
    assert m2b["caution_flags"] is None


def test_update_risk_flags_skips_unknown_ticker(tmp_db):
    cache.update_risk_flags({"999999": {"is_risk": True, "labels": ["관리"]}})
    assert cache.cache_load_meta("999999") is None
