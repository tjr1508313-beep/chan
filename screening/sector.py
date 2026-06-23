"""Backend-only sector RS snapshot helpers.

This module wires the existing screening pipeline into one pure backend entry
point so sector leadership can be inspected without Streamlit.
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from .cache import cache_load_universe, cache_save_universe
from .core import (
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
        "ranked": pd.DataFrame(),
        "sector_summary": pd.DataFrame(),
        "sector_members": pd.DataFrame(),
    }


def screen_build_sector_snapshot(
    index_code,
    period=20,
    top_n_per_sector=5,
    min_sector_size=1,
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
    is_kr = _is_kr_index(code)

    if tickers is None:
        universe, universe_source = _load_universe(code)
    else:
        universe = list(tickers)
        universe_source = "argument"

    normalized = _normalize_tickers(universe, is_kr=is_kr)
    universe_count = len(normalized)
    if max_tickers is not None:
        limit = max(int(max_tickers), 0)
        normalized = normalized[:limit]

    cfg = _default_filter_config(code)
    if filter_config:
        cfg.update(filter_config)

    if not normalized:
        return _empty_snapshot(
            code=code,
            period=period,
            cfg=cfg,
            universe_source=universe_source,
            universe_count=universe_count,
            input_count=len(normalized),
        )

    metadata = screen_build_screening_df(normalized, lookback_days=20)
    if is_kr:
        metadata = _overlay_kr_sectors(metadata)

    filtered, stats = screen_apply_filters(metadata, cfg)
    lag_passed, lag_excluded = screen_filter_by_index_lag(
        filtered.index.tolist(), code, max_lag_days=max_lag_days
    )
    ranked = screen_rank_rs(lag_passed, code, period=period, top_n=None)
    sector_summary, sector_members = screen_build_sector_rankings(
        ranked,
        metadata,
        top_n_per_sector=top_n_per_sector,
        min_sector_size=min_sector_size,
    )

    return {
        "index_code": code,
        "period": int(period),
        "filter_config": cfg,
        "filter_stats": stats,
        "lag_excluded": int(lag_excluded),
        "universe_source": universe_source,
        "universe_count": int(universe_count),
        "input_count": int(len(normalized)),
        "ranked": ranked,
        "sector_summary": sector_summary,
        "sector_members": sector_members,
    }
