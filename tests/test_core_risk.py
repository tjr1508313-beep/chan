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


import pandas as pd
import screening.core as core


def test_screening_df_includes_caution_flags():
    assert "caution_flags" in core._SCREEN_DF_COLUMNS


def test_exclude_risk_filters_is_risk_rows():
    df = pd.DataFrame(
        {
            "last_price": [100.0, 100.0],
            "avg_traded_value_20d": [1e11, 1e11],
            "max_daily_range_20d": [0.1, 0.1],
            "recent_atr_drop_mult": [0.0, 0.0],
            "market_cap": [1e12, 1e12],
            "is_china": [False, False],
            "is_risk": [False, True],
            "caution_flags": ["투자경고", "관리"],
            "name_en": ["A", "B"],
            "name_kr": ["A", "B"],
            "sector": [None, None],
            "country": ["South Korea", "South Korea"],
        },
        index=pd.Index(["000001", "000002"], name="ticker"),
    )
    cfg = core._default_config()
    cfg.update({"min_price": 0, "min_traded_value": 0, "min_market_cap": 0,
                "max_daily_range_pct": 1.0, "max_atr_drop_multiple": 0,
                "exclude_china": False, "exclude_risk": True})
    out, stats = core.screen_apply_filters(df, cfg)   # returns (df, stats) tuple
    assert "000002" not in out.index   # is_risk 제외
    assert "000001" in out.index       # 투자경고는 통과 (참고만)
    assert out.loc["000001", "caution_flags"] == "투자경고"
