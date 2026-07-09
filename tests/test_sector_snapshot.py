import importlib

import pandas as pd

import screening.sector as sector


def _sector_module():
    return importlib.import_module("screening.sector")


def _screening_df(tickers, sectors=None):
    sectors = sectors or {}
    rows = []
    for ticker in tickers:
        rows.append(
            {
                "ticker": ticker,
                "last_price": 100.0,
                "avg_traded_value_20d": 1_000_000.0,
                "market_cap": 10_000_000.0,
                "sector": sectors.get(ticker, f"{ticker}-sector"),
                "name_kr": f"{ticker}-name",
            }
        )
    return pd.DataFrame(rows).set_index("ticker")


def _ranked_df(tickers):
    return pd.DataFrame(
        [
            {
                "rank": pos,
                "ticker": ticker,
                "rs": 0.20 - pos / 100,
                "rs_weighted": 1.5 - pos / 100,
                "return_n": 0.30 - pos / 100,
                "index_return_n": 0.05,
                "last_price": 100.0,
            }
            for pos, ticker in enumerate(tickers, start=1)
        ]
    )


def _patch_pipeline(monkeypatch, sector, *, build_sectors=None):
    calls = []
    filter_stats = {"total": 0, "final": 0}

    def fail_universe_loader(index_code):
        raise AssertionError("universe loader should not be called")

    def build_screening_df(tickers, lookback_days=20):
        tickers = list(tickers)
        calls.append(("build", tickers, lookback_days))
        return _screening_df(tickers, build_sectors)

    def apply_filters(df, config=None):
        calls.append(("filter", list(df.index), config))
        stats = {"total": len(df), "final": len(df), **filter_stats}
        return df.copy(), stats

    def filter_by_index_lag(tickers, index_code, max_lag_days=0):
        tickers = list(tickers)
        calls.append(("lag", tickers, index_code, max_lag_days))
        return tickers, 0

    def rank_rs(tickers, index_code, period=20, top_n=None):
        tickers = list(tickers)
        calls.append(("rank", tickers, index_code, period, top_n))
        return _ranked_df(tickers)

    def sector_rankings(ranked, metadata, *, top_n_per_sector=5, min_sector_size=1):
        calls.append(
            (
                "sector",
                list(ranked["ticker"]),
                metadata.reset_index().to_dict("records"),
                top_n_per_sector,
                min_sector_size,
            )
        )
        summary = pd.DataFrame(
            [{"rank": 1, "sector": "Tech", "stock_count": len(ranked)}]
        )
        members = ranked[["ticker", "return_n", "rs"]].copy()
        members["sector"] = "Tech"
        return summary, members

    monkeypatch.setattr(sector, "cache_load_universe", fail_universe_loader, raising=False)
    monkeypatch.setattr(sector, "screen_build_screening_df", build_screening_df, raising=False)
    monkeypatch.setattr(sector, "screen_apply_filters", apply_filters, raising=False)
    monkeypatch.setattr(
        sector, "screen_filter_by_index_lag", filter_by_index_lag, raising=False
    )
    monkeypatch.setattr(sector, "screen_rank_rs", rank_rs, raising=False)
    monkeypatch.setattr(
        sector, "screen_build_sector_rankings", sector_rankings, raising=False
    )
    return calls


def test_snapshot_uses_explicit_tickers_and_wires_pipeline_in_order(monkeypatch):
    sector = _sector_module()
    calls = _patch_pipeline(monkeypatch, sector)

    result = sector.screen_build_sector_snapshot(
        "^IXIC",
        period=20,
        top_n_per_sector=3,
        min_sector_size=2,
        tickers=["AAA", "BBB", "CCC"],
        max_lag_days=1,
        filter_config={"min_price": 5},
    )

    assert [call[0] for call in calls] == ["build", "filter", "lag", "rank", "sector"]
    assert calls[0] == ("build", ["AAA", "BBB", "CCC"], 20)
    assert calls[1][0:2] == ("filter", ["AAA", "BBB", "CCC"])
    assert calls[1][2]["min_price"] == 5
    assert calls[2] == ("lag", ["AAA", "BBB", "CCC"], "^IXIC", 1)
    assert calls[3] == ("rank", ["AAA", "BBB", "CCC"], "^IXIC", 20, None)
    assert calls[4][3:] == (3, 2)
    assert {
        "index_code",
        "period",
        "filter_stats",
        "lag_excluded",
        "ranked",
        "sector_summary",
        "sector_members",
    }.issubset(result)
    assert result["index_code"] == "^IXIC"
    assert result["period"] == 20
    assert result["lag_excluded"] == 0
    assert list(result["ranked"]["ticker"]) == ["AAA", "BBB", "CCC"]


def test_snapshot_overlays_kr_sector_when_metadata_sector_is_blank(monkeypatch):
    sector = _sector_module()
    calls = _patch_pipeline(
        monkeypatch,
        sector,
        build_sectors={"005930": "", "000660": None},
    )

    monkeypatch.setattr(
        sector,
        "kr_get_sector",
        lambda ticker: {"005930": "Semiconductors", "000660": "Semiconductors"}.get(
            str(ticker).zfill(6)
        ),
        raising=False,
    )

    sector.screen_build_sector_snapshot("KS11", tickers=["005930", "000660"])

    sector_call = calls[-1]
    metadata = {row["ticker"]: row for row in sector_call[2]}
    assert metadata["005930"]["sector"] == "Semiconductors"
    assert metadata["000660"]["sector"] == "Semiconductors"


def test_snapshot_limits_universe_before_building_screening_df(monkeypatch):
    sector = _sector_module()
    calls = _patch_pipeline(monkeypatch, sector)

    sector.screen_build_sector_snapshot(
        "^GSPC",
        tickers=["AAA", "BBB", "CCC"],
        max_tickers=2,
    )

    assert calls[0] == ("build", ["AAA", "BBB"], 20)


def test_snapshot_returns_empty_result_when_limited_to_zero(monkeypatch):
    sector = _sector_module()

    monkeypatch.setattr(
        sector,
        "screen_build_screening_df",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("screening df should not be built")
        ),
        raising=False,
    )

    result = sector.screen_build_sector_snapshot(
        "ks11",
        tickers=["005930"],
        max_tickers=0,
    )

    assert result["index_code"] == "KS11"
    assert result["input_count"] == 0
    assert result["filter_stats"]["final"] == 0
    assert result["ranked"].empty
    assert result["sector_summary"].empty
    assert result["sector_members"].empty


def test_snapshot_falls_back_to_loader_and_saves_universe_when_cache_is_empty(
    monkeypatch,
):
    sector = _sector_module()
    calls = _patch_pipeline(monkeypatch, sector)
    universe_calls = []

    monkeypatch.setattr(
        sector,
        "cache_load_universe",
        lambda index_code: universe_calls.append(("cache_load", index_code)) or [],
        raising=False,
    )
    monkeypatch.setitem(
        sector._UNIVERSE_LOADERS,
        "^IXIC",
        lambda: universe_calls.append(("fallback", "^IXIC")) or ["AAA", "BBB"],
    )
    monkeypatch.setattr(
        sector,
        "cache_save_universe",
        lambda index_code, tickers: universe_calls.append(
            ("cache_save", index_code, list(tickers))
        )
        or len(tickers),
        raising=False,
    )

    result = sector.screen_build_sector_snapshot("^IXIC")

    assert universe_calls == [
        ("cache_load", "^IXIC"),
        ("fallback", "^IXIC"),
        ("cache_save", "^IXIC", ["AAA", "BBB"]),
    ]
    assert calls[0] == ("build", ["AAA", "BBB"], 20)
    assert list(result["ranked"]["ticker"]) == ["AAA", "BBB"]


def test_select_sector_members_filters_one_sector_case_insensitively():
    sector = _sector_module()
    members = pd.DataFrame(
        [
            {"sector": "Tech", "rank_in_sector": 2, "ticker": "BBB"},
            {"sector": "Energy", "rank_in_sector": 1, "ticker": "CCC"},
            {"sector": "Tech", "rank_in_sector": 1, "ticker": "AAA"},
        ]
    )

    selected = sector.screen_select_sector_members(members, "tech")

    assert list(selected["ticker"]) == ["AAA", "BBB"]


def test_select_sector_summary_filters_one_sector_case_insensitively():
    sector = _sector_module()
    summary = pd.DataFrame(
        [
            {"rank": 1, "sector": "Tech", "sector_score": 0.3},
            {"rank": 2, "sector": "Energy", "sector_score": 0.1},
        ]
    )

    selected = sector.screen_select_sector_summary(summary, "TECH")

    assert len(selected) == 1
    assert selected.loc[0, "sector"] == "Tech"


def test_combined_snapshot_merges_markets_with_per_market_rs(monkeypatch):
    sector = _sector_module()
    calls = _patch_pipeline(monkeypatch, sector)

    snap = sector.screen_build_combined_sector_snapshot(
        ["KS11", "KQ11"],
        period=20,
        top_n_per_sector=5,
        min_sector_size=1,
        tickers_map={"KS11": ["005930", "000660"], "KQ11": ["247540"]},
    )

    # 두 시장 ranked가 합쳐짐 (3종목)
    assert set(snap["ranked"]["ticker"]) == {"005930", "000660", "247540"}

    # RS는 각 시장 자기 지수로 계산됨 (정확)
    rank_calls = [c for c in calls if c[0] == "rank"]
    assert ("rank", ["005930", "000660"], "KS11", 20, None) in rank_calls
    assert ("rank", ["247540"], "KQ11", 20, None) in rank_calls


def test_cache_sector_snapshot_round_trip_preserves_leading_zeros(tmp_path, monkeypatch):
    import screening.cache as cache

    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "sector.db")
    cache.init_cache()

    summary = pd.DataFrame(
        [{"rank": 1, "sector": "반도체", "sector_score": 0.26, "stock_count": 21,
          "positive_ratio": 0.8, "top_ticker": "005930", "top_name": "삼성전자"}]
    )
    members = pd.DataFrame(
        [{"sector": "반도체", "rank_in_sector": 1, "ticker": "005930",
          "name_kr": "삼성전자", "return_n": 0.24, "rs": 0.04,
          "rs_weighted": 1.8, "last_price": 70000.0, "avg_traded_value_20d": 3.2e11}]
    )
    cache.cache_save_sector_snapshot("KR", 20, summary, members)

    loaded = cache.cache_load_sector_snapshot("KR")
    assert loaded["period"] == 20
    assert int(loaded["sector_summary"].iloc[0]["stock_count"]) == 21
    # 앞자리 0 보존 (005930이 5930이 되면 안 됨)
    assert str(loaded["sector_members"].iloc[0]["ticker"]) == "005930"
    assert str(loaded["sector_summary"].iloc[0]["top_ticker"]) == "005930"
    assert cache.cache_load_sector_snapshot("NOPE") is None


def _patch_rebuild_kr(monkeypatch):
    """KR 리빌드 경로를 mock으로 감싸고 (single_calls, combined_calls) 를 돌려준다.

    cache_load_universe 는 시장별로 다른 티커를 반환 → 모집단 구성 검증 가능.
    KS11 → ["005930"](코스피), KQ11 → ["247540"](코스닥).
    """
    single_calls = []
    combined_calls = []

    def fake_single(index_code, **kwargs):
        single_calls.append((index_code, kwargs))
        return {
            "sector_summary": pd.DataFrame([{"sector": "반도체"}]),
            "sector_members": pd.DataFrame([{"sector": "반도체", "ticker": "005930"}]),
        }

    def fake_combined(index_codes, **kwargs):
        combined_calls.append((index_codes, kwargs))
        return {"sector_summary": pd.DataFrame(), "sector_members": pd.DataFrame()}

    universe = {"KS11": ["005930"], "KQ11": ["247540"]}
    monkeypatch.setattr(sector, "screen_build_sector_snapshot", fake_single, raising=False)
    monkeypatch.setattr(
        sector, "screen_build_combined_sector_snapshot", fake_combined, raising=False
    )
    monkeypatch.setattr(
        sector, "cache_save_sector_snapshot", lambda *a, **k: True, raising=False
    )
    monkeypatch.setattr(
        sector, "cache_load_universe", lambda code: list(universe.get(code, [])),
        raising=False,
    )
    return single_calls, combined_calls


def test_rebuild_kr_benchmark_is_ks11_and_includes_kosdaq(monkeypatch):
    # 기본(합산): 벤치마크는 KS11 단독, 모집단은 코스피+코스닥.
    monkeypatch.setattr(sector, "_KR_SECTOR_INCLUDE_KOSDAQ", True, raising=False)
    single_calls, combined_calls = _patch_rebuild_kr(monkeypatch)

    result = sector.screen_rebuild_sector_snapshot("kr")

    assert combined_calls == []              # KQ11 지수를 벤치마크로 쓰지 않음
    assert len(single_calls) == 1
    assert single_calls[0][0] == "KS11"      # 벤치마크 = 코스피 단독
    assert single_calls[0][1]["tickers"] == ["005930", "247540"]  # 코스피+코스닥 모집단
    assert result[sector._KR_SECTOR_SCOPE] == 1


def test_rebuild_kr_kospi_only_when_flag_off(monkeypatch):
    # 되돌림 스위치: 코스닥 제외 시 모집단은 코스피 단독.
    monkeypatch.setattr(sector, "_KR_SECTOR_INCLUDE_KOSDAQ", False, raising=False)
    single_calls, combined_calls = _patch_rebuild_kr(monkeypatch)

    sector.screen_rebuild_sector_snapshot("kr")

    assert combined_calls == []
    assert single_calls[0][0] == "KS11"
    assert single_calls[0][1]["tickers"] == ["005930"]  # 코스닥 미포함
