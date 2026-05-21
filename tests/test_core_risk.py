import screening.batch_kr as batch_kr
import screening.cache as cache


def test_refresh_risk_skips_when_no_flags(tmp_path, monkeypatch):
    db = tmp_path / "c.db"
    monkeypatch.setattr(cache, "DB_PATH", db)
    cache.init_cache()
    cache.cache_save_meta("005930", {
        "name_en": "x", "name_kr": "x", "sector": None, "country": "South Korea",
        "exchange": "KOSPI", "market_cap": 1e12, "is_china": False, "is_risk": True,
        "caution_flags": "관리",
    })
    monkeypatch.setattr(batch_kr.kr_risk, "kr_fetch_risk_flags", lambda: {})
    res = batch_kr.screen_refresh_risk_kr()
    assert res["skipped"] is True
    # 빈 flags 일 때 기존 값 보존 (전체 클리어 안 함)
    assert cache.cache_load_meta("005930")["is_risk"] is True


def test_refresh_risk_applies_flags(tmp_path, monkeypatch):
    db = tmp_path / "c2.db"
    monkeypatch.setattr(cache, "DB_PATH", db)
    cache.init_cache()
    cache.cache_save_meta("005930", {
        "name_en": "x", "name_kr": "x", "sector": None, "country": "South Korea",
        "exchange": "KOSPI", "market_cap": 1e12, "is_china": False, "is_risk": False,
    })
    monkeypatch.setattr(
        batch_kr.kr_risk, "kr_fetch_risk_flags",
        lambda: {"005930": {"is_risk": True, "labels": ["관리"]}},
    )
    res = batch_kr.screen_refresh_risk_kr()
    assert res["skipped"] is False
    assert res["updated"] == 1
    m = cache.cache_load_meta("005930")
    assert m["is_risk"] is True
    assert m["caution_flags"] == "관리"
