"""스크리닝 핵심 로직 — RS 계산, 필터링, 랭킹.

통합 대비 규칙:
    - 공개 함수는 `screen_` 접두사
    - `@st.cache_data` 사용 시에도 동일 접두사 유지

핵심 개념:
    ⚠️ RS ≠ RSI(상대강도지수). 여기서 RS는 **지수 대비 종목 수익률 비율**.
    MVP 공식: `RS = (종목 N일 수익률) / (지수 N일 수익률)`
    기본 기간 20일, 사용자 조정 가능 (5~60일).

필터 조건 (모두 AND, 순서 고정):
    1. 주가 >= min_price (미국 $10 / 한국 1,000원)
    2. 20일 평균 거래대금 >= min_dollar_volume (미국 $20M / 한국 300억 원)
    3. 시가총액 >= min_market_cap (0=미적용 / 한국 권장 3e11)
    4. 관리종목/위험종목 제외 (`meta.is_risk == True` 제외)
    5. 중국기업 제외 (`is_china_ticker` 또는 `meta.is_china`) — 미국 한정
    6. 최근 20일 내 일일 변동폭 50% 이상 이력 있는 종목 제외
       - 변동폭 공식: `(High - Low) / prev_close`
       - "전일 종가 대비 당일 고저 폭" 직관에 부합, prev_close 가 NaN/0 인 행은 제외

파이프라인 분리:
    - `screen_build_screening_df(tickers)`: 캐시에서 데이터 읽어 종목별 1행으로 집계
    - `screen_apply_filters(df, config)`: 순수 pandas boolean mask 필터링

이 레이어는 **streamlit import 금지**.
"""

from __future__ import annotations

from typing import Iterable

import pandas as pd

from .cache import cache_load_index, cache_load_meta, cache_load_prices
from .china_filter import is_china_ticker


# 지수 수익률이 0 에 매우 가까우면 RS 극단값 방지를 위해 NaN 처리.
_RS_EPSILON: float = 1e-9


# ---------------------------------------------------------------------------
# 집계 — 캐시에서 필터링용 wide DataFrame 생성
# ---------------------------------------------------------------------------

_SCREEN_DF_COLUMNS = [
    "last_price",
    "avg_dollar_volume_20d",
    "max_daily_range_20d",
    "market_cap",
    "is_china",
    "is_risk",
    "name_en",
    "name_kr",
    "sector",
    "country",
]


def _max_daily_range(prices: pd.DataFrame, lookback: int) -> float:
    """최근 `lookback` 영업일 중 `(High - Low) / prev_close` 최대값.

    prev_close 가 NaN 또는 0 인 행은 계산에서 제외한다.
    유효 행이 없으면 `float('nan')` 반환.
    """
    if prices is None or prices.empty:
        return float("nan")
    if not {"High", "Low", "Close"}.issubset(prices.columns):
        return float("nan")

    tail = prices.tail(lookback + 1)  # prev_close 계산용 여유 1행
    prev_close = tail["Close"].shift(1)
    rng = (tail["High"] - tail["Low"]) / prev_close
    rng = rng.replace([float("inf"), float("-inf")], float("nan")).dropna()
    # lookback 영업일만 대상
    rng = rng.tail(lookback)
    if rng.empty:
        return float("nan")
    return float(rng.max())


def _avg_dollar_volume(prices: pd.DataFrame, lookback: int) -> float:
    """최근 `lookback` 영업일 평균 거래대금. 없으면 NaN."""
    if prices is None or prices.empty or "dollar_volume" not in prices.columns:
        return float("nan")
    tail = prices["dollar_volume"].tail(lookback).dropna()
    if tail.empty:
        return float("nan")
    return float(tail.mean())


def _last_close(prices: pd.DataFrame) -> float:
    """최근 종가. 없으면 NaN."""
    if prices is None or prices.empty or "Close" not in prices.columns:
        return float("nan")
    s = prices["Close"].dropna()
    if s.empty:
        return float("nan")
    return float(s.iloc[-1])


def screen_build_screening_df(
    tickers: Iterable[str],
    lookback_days: int = 20,
) -> pd.DataFrame:
    """캐시에서 시세/메타를 꺼내 종목별 1행 집계 DataFrame 을 만든다.

    Args:
        tickers: 티커 리스트.
        lookback_days: 거래대금 평균/변동폭 계산 윈도. 기본 20.

    Returns:
        index=ticker (대문자), columns=_SCREEN_DF_COLUMNS 의 DataFrame.
        시세/메타가 전혀 없는 티커는 조용히 건너뛴다.
    """
    rows: list[dict] = []
    seen: set[str] = set()

    for raw in tickers:
        if not raw:
            continue
        t = str(raw).strip().upper()
        if not t or t in seen:
            continue
        seen.add(t)

        # 변동폭 계산은 prev_close 용 1일 여유가 필요, 안전 여유 +5
        prices = cache_load_prices(t, days=lookback_days + 5)
        meta = cache_load_meta(t) or {}

        if (prices is None or prices.empty) and not meta:
            continue

        last_price = _last_close(prices)
        avg_dv = _avg_dollar_volume(prices, lookback_days)
        max_rng = _max_daily_range(prices, lookback_days)

        # 중국 판정: CSV + meta.country fallback
        china_by_meta = bool(meta.get("is_china")) if meta.get("is_china") is not None else False
        china_by_lookup = is_china_ticker(t, meta=meta if meta else None)
        is_china = bool(china_by_meta or china_by_lookup)

        is_risk = bool(meta.get("is_risk")) if meta.get("is_risk") is not None else False

        market_cap = meta.get("market_cap")
        if market_cap is not None:
            try:
                market_cap = float(market_cap)
            except (TypeError, ValueError):
                market_cap = None

        rows.append(
            {
                "ticker": t,
                "last_price": last_price,
                "avg_dollar_volume_20d": avg_dv,
                "max_daily_range_20d": max_rng,
                "market_cap": market_cap,
                "is_china": is_china,
                "is_risk": is_risk,
                "name_en": meta.get("name_en"),
                "name_kr": meta.get("name_kr"),
                "sector": meta.get("sector"),
                "country": meta.get("country"),
            }
        )

    if not rows:
        return pd.DataFrame(columns=_SCREEN_DF_COLUMNS).rename_axis("ticker")

    df = pd.DataFrame(rows).set_index("ticker")
    # 컬럼 순서 고정
    return df[_SCREEN_DF_COLUMNS]


# ---------------------------------------------------------------------------
# 필터링 — 순수 pandas
# ---------------------------------------------------------------------------

def _default_config() -> dict:
    return {
        "min_price": 10.0,
        "min_dollar_volume": 20_000_000.0,
        "min_market_cap": 0.0,           # 0 = 미적용. 한국주식은 3,000억(3e11) 권장
        "max_daily_range_pct": 0.50,
        "exclude_china": True,
        "exclude_risk": True,
    }


def screen_apply_filters(
    df: pd.DataFrame,
    config: dict | None = None,
) -> tuple[pd.DataFrame, dict]:
    """필터 6종 순차 적용 (주가 → 거래대금 → 시총 → 관리 → 중국 → 변동성).

    Args:
        df: `screen_build_screening_df()` 결과 형태의 wide DataFrame.
            필요한 컬럼: last_price, avg_dollar_volume_20d, max_daily_range_20d,
                         is_china, is_risk.
        config: 필터 기준. `None` 이면 기본값.

    Returns:
        (filtered_df, stats). stats 는 각 단계 누적 잔존 수::

            {
                "total": 3500,
                "after_price": 2800,
                "after_volume": 1200,
                "after_risk": 1180,
                "after_china": 1150,
                "after_volatility": 800,
                "final": 800,
            }
    """
    cfg = {**_default_config(), **(config or {})}

    stats: dict[str, int] = {"total": int(len(df))}

    if df is None or df.empty:
        for key in ("after_price", "after_volume", "after_market_cap", "after_risk", "after_china", "after_volatility", "final"):
            stats[key] = 0
        return df.iloc[0:0].copy() if df is not None else pd.DataFrame(columns=_SCREEN_DF_COLUMNS), stats

    current = df

    # 1) 주가
    mask_price = current["last_price"].fillna(-1.0) >= float(cfg["min_price"])
    current = current[mask_price]
    stats["after_price"] = int(len(current))

    # 2) 거래대금
    mask_vol = current["avg_dollar_volume_20d"].fillna(-1.0) >= float(cfg["min_dollar_volume"])
    current = current[mask_vol]
    stats["after_volume"] = int(len(current))

    # 3) 시가총액 (min_market_cap > 0 일 때만 적용)
    min_mc = float(cfg.get("min_market_cap", 0.0))
    if min_mc > 0 and "market_cap" in current.columns:
        mask_mc = current["market_cap"].fillna(-1.0) >= min_mc
        current = current[mask_mc]
    stats["after_market_cap"] = int(len(current))

    # 4) 관리/위험종목
    if cfg.get("exclude_risk", True):
        # is_risk True 인 종목 제외, NaN/None 은 포함(보수적으로 통과)
        risk_flag = current["is_risk"].fillna(False).astype(bool)
        current = current[~risk_flag]
    stats["after_risk"] = int(len(current))

    # 5) 중국기업
    if cfg.get("exclude_china", True):
        china_flag = current["is_china"].fillna(False).astype(bool)
        current = current[~china_flag]
    stats["after_china"] = int(len(current))

    # 6) 변동성 — lookback 내 일일 변동폭 >= max_daily_range_pct 이면 제외
    max_rng = float(cfg["max_daily_range_pct"])
    # NaN (데이터 부족) 은 통과시킴
    rng_values = current["max_daily_range_20d"]
    mask_vola = ~(rng_values.fillna(-1.0) >= max_rng)
    current = current[mask_vola]
    stats["after_volatility"] = int(len(current))

    stats["final"] = int(len(current))
    return current, stats


# ---------------------------------------------------------------------------
# RS 계산 — Phase 1.5 에서 구현
# ---------------------------------------------------------------------------

def _period_return(series: pd.Series, period: int) -> float:
    """N영업일 수익률: `close[-1] / close[-period-1] - 1`. 데이터 부족 시 NaN."""
    s = series.dropna()
    if len(s) < period + 1:
        return float("nan")
    prev = float(s.iloc[-period - 1])
    last = float(s.iloc[-1])
    if prev == 0 or pd.isna(prev) or pd.isna(last):
        return float("nan")
    return last / prev - 1.0


def _index_return(index_prices: pd.DataFrame, period: int) -> float:
    """지수 N일 수익률. epsilon 이하이면 NaN (RS 극단값 방지)."""
    if index_prices is None or index_prices.empty or "Close" not in index_prices.columns:
        return float("nan")
    r = _period_return(index_prices["Close"], period)
    if pd.isna(r) or abs(r) < _RS_EPSILON:
        return float("nan")
    return r


def screen_calc_rs(
    prices: pd.DataFrame,
    index_prices: pd.DataFrame,
    period: int = 20,
) -> pd.Series:
    """상대강도(RS)를 계산한다.

    RS = (종목 N일 수익률) / (지수 N일 수익률)

    Args:
        prices: 종목 일봉 DataFrame. 두 형태 모두 지원:
            - 단일 종목: `Close` 컬럼을 포함한 OHLCV DataFrame
            - 여러 종목 wide: columns=티커, 값=종가
        index_prices: 기준 지수 일봉 DataFrame (`Close` 컬럼 필수).
        period: RS 계산 기간(영업일 기준). 기본 20일.

    Returns:
        티커별 RS 점수 Series. NaN 포함 가능. 호출자가
        `.dropna().sort_values(ascending=False)` 로 랭킹.

        단일 종목 입력 시 길이 1, 이름 없는 Series 반환.

    주의:
        지수 수익률이 음수일 때 종목도 음수면 RS > 0 이 된다(의도된 동작).
        다만 지수가 음수/양수 경계로 뒤바뀌면 순위도 역전될 수 있으니
        UI 에서 해석에 주의.
    """
    idx_return = _index_return(index_prices, period)

    if prices is None or prices.empty:
        return pd.Series([], dtype=float)

    is_single = "Close" in prices.columns
    if is_single:
        stock_return = _period_return(prices["Close"], period)
        rs = float("nan") if pd.isna(idx_return) else stock_return / idx_return
        return pd.Series([rs], dtype=float)

    # wide: columns=티커, 값=close
    rs_map: dict[str, float] = {}
    for col in prices.columns:
        stock_return = _period_return(prices[col], period)
        if pd.isna(idx_return) or pd.isna(stock_return):
            rs_map[str(col)] = float("nan")
        else:
            rs_map[str(col)] = stock_return / idx_return
    return pd.Series(rs_map, dtype=float)


# ---------------------------------------------------------------------------
# RS 랭킹 — 캐시에서 바로 Top N 추출
# ---------------------------------------------------------------------------

_RANK_DF_COLUMNS = [
    "rank",
    "ticker",
    "rs",
    "return_n",
    "index_return_n",
    "last_price",
]


def screen_rank_rs(
    tickers: Iterable[str],
    index_code: str,
    period: int = 20,
    top_n: int = 20,
) -> pd.DataFrame:
    """캐시에서 티커 시세/지수를 꺼내 RS Top N 랭킹 DataFrame 을 반환한다.

    Args:
        tickers: 대상 티커 (보통 필터 통과 종목).
        index_code: 기준 지수 코드 (예: `^IXIC`, `^GSPC`).
        period: RS 계산 기간. 기본 20.
        top_n: 상위 N개.

    Returns:
        columns=_RANK_DF_COLUMNS 의 DataFrame. RS 내림차순, rank 1부터.
        데이터 부족 종목은 NaN 제거. 지수 수익률이 epsilon 근처이면
        모든 RS 가 NaN → 빈 DataFrame.
    """
    # 여유 +10 영업일 (주말/공휴일 흡수)
    days = period + 10

    index_df = cache_load_index(index_code, days=days)
    idx_return = _index_return(index_df, period)

    rows: list[dict] = []
    seen: set[str] = set()

    for raw in tickers:
        if not raw:
            continue
        t = str(raw).strip().upper()
        if not t or t in seen:
            continue
        seen.add(t)

        prices = cache_load_prices(t, days=days)
        if prices is None or prices.empty:
            continue

        stock_return = _period_return(prices["Close"], period)
        if pd.isna(idx_return) or pd.isna(stock_return):
            continue
        rs = stock_return / idx_return

        last_price = _last_close(prices)
        rows.append(
            {
                "ticker": t,
                "rs": float(rs),
                "return_n": float(stock_return),
                "index_return_n": float(idx_return),
                "last_price": last_price,
            }
        )

    if not rows:
        return pd.DataFrame(columns=_RANK_DF_COLUMNS)

    df = pd.DataFrame(rows)
    df = df.sort_values("rs", ascending=False, kind="mergesort").reset_index(drop=True)
    df = df.head(top_n).copy()
    df.insert(0, "rank", range(1, len(df) + 1))
    return df[_RANK_DF_COLUMNS]


# ---------------------------------------------------------------------------
# 사용 예시 (Phase 1.6 UI 에서 조합):
#   df = screen_build_screening_df(tickers)
#   filtered, stats = screen_apply_filters(df, config)
#   ranked = screen_rank_rs(filtered.index.tolist(), '^IXIC', period=20, top_n=20)
# ---------------------------------------------------------------------------
