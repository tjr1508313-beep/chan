"""Backend-only sector RS snapshot helpers.

This module wires the existing screening pipeline into one pure backend entry
point so sector leadership can be inspected without Streamlit.
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from .cache import (
    cache_load_universe,
    cache_save_sector_snapshot,
    cache_save_universe,
)
from .core import (
    _RANK_DF_COLUMNS,
    _SECTOR_MEMBER_COLUMNS,
    _SECTOR_SUMMARY_COLUMNS,
    screen_apply_filters,
    screen_build_screening_df,
    screen_build_sector_rankings,
    screen_filter_by_index_lag,
    screen_rank_rs,
)
from .data import us_get_nasdaq_tickers, us_get_sp500_tickers
from .data_kr import kr_get_kosdaq_tickers, kr_get_kospi_tickers, kr_get_sector


_US_DEFAULT_FILTER = {
    "min_price": 10.0,
    "min_traded_value": 20_000_000.0,
    "min_market_cap": 0.0,
    "max_daily_range_pct": 0.50,
    "max_atr_drop_multiple": 2.5,
    "exclude_china": True,
    "exclude_risk": True,
}

_KR_DEFAULT_FILTER = {
    "min_price": 1_000.0,
    "min_traded_value": 30_000_000_000.0,
    "min_market_cap": 300_000_000_000.0,
    "max_daily_range_pct": 0.50,
    "max_atr_drop_multiple": 2.5,
    "exclude_china": False,
    "exclude_risk": True,
}

_UNIVERSE_LOADERS = {
    "^IXIC": us_get_nasdaq_tickers,
    "^GSPC": us_get_sp500_tickers,
    "KS11": kr_get_kospi_tickers,
    "KQ11": kr_get_kosdaq_tickers,
}

_KR_INDEX_CODES = {"KS11", "KQ11"}

_EMPTY_FILTER_STATS = {
    "total": 0,
    "after_price": 0,
    "after_volume": 0,
    "after_market_cap": 0,
    "after_risk": 0,
    "after_china": 0,
    "after_volatility": 0,
    "after_atr_drop": 0,
    "final": 0,
}


def _normalize_index_code(index_code: str) -> str:
    return str(index_code).strip().upper()


def _is_kr_index(index_code: str) -> bool:
    return _normalize_index_code(index_code) in _KR_INDEX_CODES


def _default_filter_config(index_code: str) -> dict:
    base = _KR_DEFAULT_FILTER if _is_kr_index(index_code) else _US_DEFAULT_FILTER
    return dict(base)


def _normalize_tickers(tickers: Iterable[str], *, is_kr: bool) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for ticker in tickers:
        if ticker is None:
            continue
        text = str(ticker).strip()
        if not text:
            continue
        norm = text.zfill(6) if is_kr and text.isdigit() else text.upper()
        if norm in seen:
            continue
        seen.add(norm)
        out.append(norm)
    return out


def _load_universe(index_code: str) -> tuple[list[str], str]:
    code = _normalize_index_code(index_code)
    tickers = cache_load_universe(code)
    if tickers:
        return tickers, "cache"

    loader = _UNIVERSE_LOADERS.get(code.upper())
    if loader is None:
        return [], "none"

    tickers = loader()
    if tickers:
        cache_save_universe(code, tickers)
    return tickers, "source"


def _overlay_kr_sectors(metadata: pd.DataFrame) -> pd.DataFrame:
    if metadata is None or metadata.empty:
        return metadata
    out = metadata.copy()
    if "sector" not in out.columns:
        out["sector"] = None
    for ticker in out.index.astype(str):
        code = ticker.strip().zfill(6)
        if len(code) != 6 or not code.isdigit():
            continue
        sector = kr_get_sector(code)
        if sector:
            out.loc[ticker, "sector"] = sector
    return out


def _empty_snapshot(
    *,
    code: str,
    period: int,
    cfg: dict,
    universe_source: str,
    universe_count: int,
    input_count: int,
) -> dict:
    return {
        "index_code": code,
        "period": int(period),
        "filter_config": cfg,
        "filter_stats": dict(_EMPTY_FILTER_STATS),
        "lag_excluded": 0,
        "universe_source": universe_source,
        "universe_count": int(universe_count),
        "input_count": int(input_count),
        "ranked": pd.DataFrame(columns=_RANK_DF_COLUMNS),
        "sector_summary": pd.DataFrame(columns=_SECTOR_SUMMARY_COLUMNS),
        "sector_members": pd.DataFrame(columns=_SECTOR_MEMBER_COLUMNS),
    }


def screen_select_sector_members(
    sector_members: pd.DataFrame,
    sector: str,
    *,
    top_n: int | None = None,
    case_sensitive: bool = False,
) -> pd.DataFrame:
    """Return the leaders for one sector from a sector snapshot members table."""
    if sector_members is None or sector_members.empty:
        return pd.DataFrame(columns=_SECTOR_MEMBER_COLUMNS)
    if "sector" not in sector_members.columns:
        raise ValueError("sector_members에 'sector' 컬럼이 필요합니다.")

    target = str(sector).strip()
    if not target:
        return pd.DataFrame(columns=sector_members.columns)

    sector_values = sector_members["sector"].fillna("").astype(str).str.strip()
    if case_sensitive:
        selected = sector_members[sector_values == target].copy()
    else:
        selected = sector_members[sector_values.str.casefold() == target.casefold()].copy()

    selected = selected.sort_values(
        ["rank_in_sector"], ascending=[True], kind="mergesort"
    ).reset_index(drop=True)
    if top_n is not None:
        selected = selected.head(max(int(top_n), 0))
    return selected


def screen_select_sector_summary(
    sector_summary: pd.DataFrame,
    sector: str,
    *,
    case_sensitive: bool = False,
) -> pd.DataFrame:
    """Return the summary row for one sector from a sector snapshot summary table."""
    if sector_summary is None or sector_summary.empty:
        return pd.DataFrame(columns=_SECTOR_SUMMARY_COLUMNS)
    if "sector" not in sector_summary.columns:
        raise ValueError("sector_summary에 'sector' 컬럼이 필요합니다.")

    target = str(sector).strip()
    if not target:
        return pd.DataFrame(columns=sector_summary.columns)

    sector_values = sector_summary["sector"].fillna("").astype(str).str.strip()
    if case_sensitive:
        return sector_summary[sector_values == target].copy().reset_index(drop=True)
    return sector_summary[
        sector_values.str.casefold() == target.casefold()
    ].copy().reset_index(drop=True)


def _build_index_ranked(
    index_code,
    period,
    filter_config,
    tickers,
    max_tickers,
    max_lag_days,
):
    """단일 지수의 (ranked, metadata, stats, cfg, source, universe_count, lag_excluded, input_count).

    ranked는 해당 지수 대비 RS로 산출되므로 시장별로 정확하다. 시장 통합 스냅샷이
    각 시장에서 이 함수를 호출한 뒤 ranked/metadata를 합친다.
    """
    code = _normalize_index_code(index_code)
    is_kr = _is_kr_index(code)

    if tickers is None:
        universe, universe_source = _load_universe(code)
    else:
        universe = list(tickers)
        universe_source = "argument"

    normalized = _normalize_tickers(universe, is_kr=is_kr)
    universe_count = len(normalized)
    if max_tickers is not None:
        normalized = normalized[: max(int(max_tickers), 0)]

    cfg = _default_filter_config(code)
    if filter_config:
        cfg.update(filter_config)

    if not normalized:
        return (
            pd.DataFrame(columns=_RANK_DF_COLUMNS), pd.DataFrame(),
            dict(_EMPTY_FILTER_STATS), cfg, universe_source, universe_count, 0, 0,
        )

    metadata = screen_build_screening_df(normalized, lookback_days=20)
    if is_kr:
        metadata = _overlay_kr_sectors(metadata)

    filtered, stats = screen_apply_filters(metadata, cfg)
    lag_passed, lag_excluded = screen_filter_by_index_lag(
        filtered.index.tolist(), code, max_lag_days=max_lag_days
    )
    ranked = screen_rank_rs(lag_passed, code, period=period, top_n=None)
    return (
        ranked, metadata, stats, cfg, universe_source,
        universe_count, int(lag_excluded), len(normalized),
    )


def screen_build_sector_snapshot(
    index_code,
    period=20,
    top_n_per_sector=5,
    min_sector_size=3,
    tickers=None,
    max_lag_days=0,
    filter_config=None,
    max_tickers=None,
):
    """Build a backend-only sector leadership snapshot.

    The returned DataFrames are intentionally left as pandas objects so callers
    can render, inspect, or persist them without losing dtypes.
    """
    code = _normalize_index_code(index_code)
    (
        ranked, metadata, stats, cfg, universe_source,
        universe_count, lag_excluded, input_count,
    ) = _build_index_ranked(code, period, filter_config, tickers, max_tickers, max_lag_days)

    if input_count == 0:
        return _empty_snapshot(
            code=code, period=period, cfg=cfg,
            universe_source=universe_source, universe_count=universe_count, input_count=0,
        )

    sector_summary, sector_members = screen_build_sector_rankings(
        ranked, metadata,
        top_n_per_sector=top_n_per_sector, min_sector_size=min_sector_size,
    )
    return {
        "index_code": code,
        "period": int(period),
        "filter_config": cfg,
        "filter_stats": stats,
        "lag_excluded": int(lag_excluded),
        "universe_source": universe_source,
        "universe_count": int(universe_count),
        "input_count": int(input_count),
        "ranked": ranked,
        "sector_summary": sector_summary,
        "sector_members": sector_members,
    }


def screen_build_combined_sector_snapshot(
    index_codes,
    period=20,
    top_n_per_sector=5,
    min_sector_size=3,
    tickers_map=None,
    filter_config=None,
    max_tickers=None,
    max_lag_days=0,
):
    """여러 지수(예: 코스피+코스닥)를 합쳐 섹터를 재집계.

    각 지수는 자기 지수 대비 RS로 ranked를 만든 뒤(시장별 정확) ranked/metadata를 합쳐
    한 번에 섹터 랭킹을 구성한다. 각 종목 rs는 이미 자기 시장 지수 대비라 시장 통합에 영향 없음.
    """
    codes = [_normalize_index_code(c) for c in index_codes]
    ranked_frames: list[pd.DataFrame] = []
    meta_frames: list[pd.DataFrame] = []
    combined_stats: dict[str, float] = {}

    for code in codes:
        tks = tickers_map.get(code) if tickers_map else None
        ranked, metadata, stats, *_rest = _build_index_ranked(
            code, period, filter_config, tks, max_tickers, max_lag_days
        )
        if ranked is not None and not ranked.empty:
            ranked_frames.append(ranked)
        if metadata is not None and not metadata.empty:
            meta_frames.append(metadata)
        for key, value in (stats or {}).items():
            if isinstance(value, (int, float)):
                combined_stats[key] = combined_stats.get(key, 0) + value

    ranked_all = (
        pd.concat(ranked_frames, ignore_index=True)
        if ranked_frames else pd.DataFrame(columns=_RANK_DF_COLUMNS)
    )
    meta_all = pd.concat(meta_frames) if meta_frames else pd.DataFrame()
    if not meta_all.empty:
        meta_all = meta_all[~meta_all.index.duplicated(keep="first")]

    sector_summary, sector_members = screen_build_sector_rankings(
        ranked_all, meta_all,
        top_n_per_sector=top_n_per_sector, min_sector_size=min_sector_size,
    )
    return {
        "index_code": "+".join(codes),
        "period": int(period),
        "filter_config": dict(filter_config or {}),
        "filter_stats": combined_stats,
        "lag_excluded": int(combined_stats.get("lag_excluded", 0)),
        "ranked": ranked_all,
        "sector_summary": sector_summary,
        "sector_members": sector_members,
    }


# ---------------------------------------------------------------------------
# 새로고침용 precompute (섹터 화면은 이 결과를 읽기만 한다)
# ---------------------------------------------------------------------------

SECTOR_SNAPSHOT_PERIOD = 20  # 섹터 화면 고정 기준: 20일 수익률

# 섹터 화면용 "느슨 필터" — 섹터 폭을 넓게 보되, 초저시총 급등주가 섹터 점수를
# 왜곡(예: 비금속 +136%)하지 않도록 시총·거래대금 하한과 배지 제외를 둔다.
_KR_SECTOR_FILTER = {
    "min_traded_value": 100 * 1e8,       # 100억 원 (초저거래대금 컷)
    "min_market_cap": 3_000 * 1e8,       # 3,000억 원 (초저시총 컷)
    "exclude_risk": True,
    "exclude_caution": True,             # 투자경고/투자주의/단기과열 등 배지 종목 제외
    "exclude_china": False,
    "max_daily_range_pct": 0.50,
    "max_atr_drop_multiple": 2.5,
}
_US_SECTOR_FILTER = {
    "min_traded_value": 10_000_000.0,    # $10M ($5M → 상향)
    "min_market_cap": 300_000_000.0,     # $300M (0 → 부활: 초저시총 컷)
    "exclude_risk": True,
    "exclude_caution": True,             # 메타에 caution_flags 있으면 제외(없으면 무영향)
    "exclude_china": True,
    "max_daily_range_pct": 0.50,
    "max_atr_drop_multiple": 2.5,
}

_KR_SECTOR_SCOPE = "KR"


def sector_snapshot_scope(index_code: str) -> str:
    """지수 코드 → 저장 scope. 한국은 코스피+코스닥 합산이라 단일 'KR'."""
    code = _normalize_index_code(index_code)
    return _KR_SECTOR_SCOPE if _is_kr_index(code) else f"US_{code}"


def screen_rebuild_sector_snapshot(
    market: str,
    period: int = SECTOR_SNAPSHOT_PERIOD,
    min_sector_size: int = 3,
) -> dict:
    """새로고침 때 호출: 섹터 스냅샷(요약+멤버 전체)을 계산해 DB에 저장.

    market="kr" → 코스피(KS11) 단독 1개(scope 'KR'). 코스닥은 제외(추후 별도).
    market="us" → 나스닥/S&P500 각각(scope 'US_^IXIC'/'US_^GSPC').
    """
    saved: dict[str, int] = {}
    if str(market).lower() == "kr":
        # 코스피(KS11) 단독으로 섹터 계산. 코스닥은 이번엔 제외(추후 별도).
        ks = cache_load_universe("KS11") or []
        snap = screen_build_sector_snapshot(
            "KS11",
            period=period,
            top_n_per_sector=5,
            min_sector_size=min_sector_size,
            tickers=ks,
            filter_config=dict(_KR_SECTOR_FILTER),
        )
        cache_save_sector_snapshot(
            _KR_SECTOR_SCOPE, period, snap["sector_summary"], snap["sector_members"]
        )
        saved[_KR_SECTOR_SCOPE] = int(len(snap["sector_summary"]))
    else:
        for code in ("^IXIC", "^GSPC"):
            tickers = cache_load_universe(code) or []
            snap = screen_build_sector_snapshot(
                code,
                period=period,
                top_n_per_sector=5,
                min_sector_size=min_sector_size,
                tickers=tickers,
                filter_config=dict(_US_SECTOR_FILTER),
            )
            scope = f"US_{code}"
            cache_save_sector_snapshot(
                scope, period, snap["sector_summary"], snap["sector_members"]
            )
            saved[scope] = int(len(snap["sector_summary"]))
    return saved
