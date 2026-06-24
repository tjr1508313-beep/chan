"""스크리닝 핵심 로직 — RS 계산, 필터링, 랭킹.

통합 대비 규칙:
    - 공개 함수는 `screen_` 접두사
    - `@st.cache_data` 사용 시에도 동일 접두사 유지

핵심 개념:
    ⚠️ RS ≠ RSI(상대강도지수). 여기서 RS는 **지수 대비 초과수익률**.
    공식: `RS = 종목 N일 수익률 - 지수 N일 수익률`
    기준지수와 수익률이 같으면 0, 더 강하면 양수, 더 약하면 음수.
    기본 기간 20일, 사용자 조정 가능 (5~60일).

필터 조건 (모두 AND, 순서 고정):
    1. 주가 >= min_price (미국 $10 / 한국 1,000원)
    2. 20일 평균 거래대금 >= min_traded_value (미국 $20M / 한국 300억 원)
    3. 시가총액 >= min_market_cap (0=미적용 / 한국 권장 3e11)
    4. 관리종목/위험종목 제외 (`meta.is_risk == True` 제외)
    5. 중국기업 제외 (`is_china_ticker` 또는 `meta.is_china`) — 미국 한정
    6. 최근 20일 내 일일 변동폭 50% 이상 이력 있는 종목 제외
       - 변동폭 공식: `(High - Low) / prev_close`
       - "전일 종가 대비 당일 고저 폭" 직관에 부합, prev_close 가 NaN/0 인 행은 제외
    7. 최근 1~2일(D-0/D-1) 종가 하락폭이 9일 ATR × `max_atr_drop_multiple` 이상이면 제외
       - 분모는 **직전일까지의 ATR9** — 큰 하락이 당일 ATR에 즉시 반영되어 필터가 무력화되는 lookahead bias 회피
       - `0` 또는 `None` 이면 비활성

파이프라인 분리:
    - `screen_build_screening_df(tickers)`: 캐시에서 데이터 읽어 종목별 1행으로 집계
    - `screen_apply_filters(df, config)`: 순수 pandas boolean mask 필터링

이 레이어는 **streamlit import 금지**.
"""

from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from .cache import (
    cache_get_all_last_price_dates,
    cache_get_last_index_date,
    cache_load_computed_metrics,
    cache_load_index,
    cache_load_meta_bulk,
    cache_load_prices_bulk,
    cache_load_stock_returns,
    cache_save_computed_snapshot,
)
from .china_filter import is_china_ticker


# Minervini 가중 RS 기간·가중치 (63/126/189/252 영업일)
_WEIGHTED_PERIODS: list[tuple[int, float]] = [
    (63, 0.4),
    (126, 0.2),
    (189, 0.2),
    (252, 0.2),
]
# 가중 RS 계산에 필요한 최소 데이터 행 수 (252 + 1)
_WEIGHTED_MIN_ROWS: int = 253


# ---------------------------------------------------------------------------
# 집계 — 캐시에서 필터링용 wide DataFrame 생성
# ---------------------------------------------------------------------------

_SCREEN_DF_COLUMNS = [
    "last_price",
    "avg_traded_value_20d",
    "max_daily_range_20d",
    "recent_atr_drop_mult",
    "market_cap",
    "is_china",
    "is_risk",
    "caution_flags",
    "name_en",
    "name_kr",
    "sector",
    "country",
]


def calc_wilder_atr(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 9
) -> pd.Series:
    """Wilder's ATR.

    TR_t  = max(H-L, |H - prevC|, |L - prevC|)
    ATR_t = (ATR_{t-1} * (period - 1) + TR_t) / period
    초기값: 첫 `period` 일의 TR 단순평균으로 부트스트랩.

    streamlit-free 순수 계산 함수. UI 차트와 필터 헬퍼가 공유.
    """
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    n = len(tr)
    atr_arr = np.full(n, np.nan, dtype=float)
    if n < period:
        return pd.Series(atr_arr, index=tr.index, dtype=float)

    # numpy 배열 위에서 Wilder 평활(순차 점화식)을 계산 — pandas .iloc[] 인덱싱
    # 오버헤드 제거. 전 종목 루프(수천 회 호출)에서 큰 차이.
    tr_arr = tr.to_numpy(dtype=float)
    init_slice = tr_arr[1 : period + 1]
    initial = np.nanmean(init_slice) if init_slice.size else np.nan
    atr_arr[period] = initial
    for i in range(period + 1, n):
        prev_atr = atr_arr[i - 1]
        tr_i = tr_arr[i]
        if np.isnan(prev_atr) or np.isnan(tr_i):
            continue
        atr_arr[i] = (prev_atr * (period - 1) + tr_i) / period
    return pd.Series(atr_arr, index=tr.index, dtype=float)


def _recent_atr_drop_multiple(
    prices: pd.DataFrame, atr_period: int = 9, lookback: int = 2
) -> float:
    """최근 `lookback`일 중 `(prev_close - close) / atr_prev` 최대값.

    각 봉의 분모는 **그 봉의 직전일까지의 ATR9** — 큰 하락이 당일 ATR에 즉시
    반영되어 필터가 무력화되는 lookahead bias 회피용.
    `atr_prev` 가 0 또는 NaN 인 행은 제외. 유효 데이터가 없으면 NaN.
    """
    if prices is None or prices.empty:
        return float("nan")
    if not {"High", "Low", "Close"}.issubset(prices.columns):
        return float("nan")
    # ATR 부트스트랩(첫 period+1 일) + shift(1) + lookback 봉 필요
    if len(prices) < atr_period + lookback + 1:
        return float("nan")

    atr = calc_wilder_atr(prices["High"], prices["Low"], prices["Close"], atr_period)
    close = prices["Close"]
    prev_close = close.shift(1)
    atr_prev = atr.shift(1)

    drop = prev_close - close  # 양수 = 하락
    valid = atr_prev > 0
    ratio = drop.where(valid) / atr_prev.where(valid)
    recent = ratio.tail(lookback).dropna()
    if recent.empty:
        return float("nan")
    return float(recent.max())


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


def _avg_traded_value(prices: pd.DataFrame, lookback: int) -> float:
    """최근 `lookback` 영업일 평균 거래대금 (USD/KRW). 없으면 NaN."""
    if prices is None or prices.empty or "traded_value" not in prices.columns:
        return float("nan")
    tail = prices["traded_value"].tail(lookback).dropna()
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
    use_snapshot: bool = True,
) -> pd.DataFrame:
    """캐시에서 시세/메타를 꺼내 종목별 1행 집계 DataFrame 을 만든다.

    Args:
        tickers: 티커 리스트.
        lookback_days: 거래대금 평균/변동폭 계산 윈도. 기본 20.

    Returns:
        index=ticker (대문자), columns=_SCREEN_DF_COLUMNS 의 DataFrame.
        시세/메타가 전혀 없는 티커는 조용히 건너뛴다.
    """
    norm_tickers = [str(t).strip().upper() for t in tickers if t and str(t).strip()]
    meta_map = cache_load_meta_bulk(norm_tickers)
    if use_snapshot:
        computed = cache_load_computed_metrics(norm_tickers)
        if set(norm_tickers).issubset(computed.index):
            rows = []
            for t, metric in computed.iterrows():
                meta = meta_map.get(t) or {}
                rows.append(
                    {
                        "ticker": t,
                        "last_price": metric.get("last_price"),
                        "avg_traded_value_20d": metric.get("avg_traded_value_20d"),
                        "max_daily_range_20d": metric.get("max_daily_range_20d"),
                        "recent_atr_drop_mult": metric.get("recent_atr_drop_mult"),
                        "market_cap": meta.get("market_cap"),
                        "is_china": bool(
                            meta.get("is_china") or is_china_ticker(t, meta=meta or None)
                        ),
                        "is_risk": bool(meta.get("is_risk")),
                        "caution_flags": meta.get("caution_flags"),
                        "name_en": meta.get("name_en"),
                        "name_kr": meta.get("name_kr"),
                        "sector": meta.get("sector"),
                        "country": meta.get("country"),
                    }
                )
            return pd.DataFrame(rows).set_index("ticker")[_SCREEN_DF_COLUMNS]

    rows: list[dict] = []
    seen: set[str] = set()

    # 종목별 개별 쿼리(2회×수천종목) 대신 일괄 조회 — 커넥션/왕복 오버헤드 제거.
    # 변동폭 계산은 prev_close 용 1일 여유가 필요, 안전 여유 +5
    prices_map = cache_load_prices_bulk(norm_tickers, days=lookback_days + 5)
    empty_prices = pd.DataFrame(
        columns=["Open", "High", "Low", "Close", "Volume", "traded_value"]
    )

    for t in norm_tickers:
        if t in seen:
            continue
        seen.add(t)

        prices = prices_map.get(t, empty_prices)
        meta = meta_map.get(t) or {}

        if prices.empty and not meta:
            continue

        last_price = _last_close(prices)
        avg_tv = _avg_traded_value(prices, lookback_days)
        max_rng = _max_daily_range(prices, lookback_days)
        recent_drop_mult = _recent_atr_drop_multiple(prices, atr_period=9, lookback=2)

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
                "avg_traded_value_20d": avg_tv,
                "max_daily_range_20d": max_rng,
                "recent_atr_drop_mult": recent_drop_mult,
                "market_cap": market_cap,
                "is_china": is_china,
                "is_risk": is_risk,
                "caution_flags": meta.get("caution_flags"),
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


def screen_rebuild_computed_snapshot(tickers: Iterable[str]) -> dict[str, int]:
    """원시 일봉에서 화면 표시용 지표와 5~60일 수익률을 미리 계산해 저장."""
    norm_tickers = sorted(
        {str(t).strip().upper() for t in tickers if t and str(t).strip()}
    )
    if not norm_tickers:
        return {"metrics": 0, "returns": 0}

    prices_map = cache_load_prices_bulk(norm_tickers, days=_WEIGHTED_MIN_ROWS + 10)
    metric_rows: list[dict] = []
    return_rows: list[dict] = []

    for ticker in norm_tickers:
        prices = prices_map.get(ticker)
        if prices is None or prices.empty:
            metric_rows.append(
                {
                    "ticker": ticker,
                    "as_of_date": None,
                    "last_price": float("nan"),
                    "avg_traded_value_20d": float("nan"),
                    "max_daily_range_20d": float("nan"),
                    "recent_atr_drop_mult": float("nan"),
                    "rs_weighted": float("nan"),
                    "below_ma5": False,
                }
            )
            continue
        close = prices["Close"].dropna()
        last_price = _last_close(prices)
        below_ma5 = False
        if len(close) >= 5:
            ma5 = float(close.tail(5).mean())
            below_ma5 = bool(last_price < ma5) if pd.notna(last_price) else False
        metric_rows.append(
            {
                "ticker": ticker,
                "as_of_date": prices.index[-1].strftime("%Y-%m-%d"),
                "last_price": last_price,
                "avg_traded_value_20d": _avg_traded_value(prices, 20),
                "max_daily_range_20d": _max_daily_range(prices, 20),
                "recent_atr_drop_mult": _recent_atr_drop_multiple(prices, 9, 2),
                "rs_weighted": _calc_weighted_rs(prices["Close"]),
                "below_ma5": below_ma5,
            }
        )
        for period in range(5, 61):
            value = _period_return(prices["Close"], period)
            if pd.notna(value):
                return_rows.append(
                    {"ticker": ticker, "period": period, "return_n": float(value)}
                )

    metrics = pd.DataFrame(metric_rows)
    if not metrics.empty:
        metrics = metrics.set_index("ticker")
    returns = pd.DataFrame(return_rows, columns=["ticker", "period", "return_n"])
    cache_save_computed_snapshot(metrics, returns, norm_tickers)
    return {"metrics": len(metric_rows), "returns": len(return_rows)}


# ---------------------------------------------------------------------------
# 필터링 — 순수 pandas
# ---------------------------------------------------------------------------

def _default_config() -> dict:
    return {
        "min_price": 10.0,
        "min_traded_value": 20_000_000.0,
        "min_market_cap": 0.0,           # 0 = 미적용. 한국주식은 3,000억(3e11) 권장
        "max_daily_range_pct": 0.50,
        "max_atr_drop_multiple": 2.5,    # 0 = 비활성. D-0/D-1 종가 하락 / ATR9_prev
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
            필요한 컬럼: last_price, avg_traded_value_20d, max_daily_range_20d,
                         is_china, is_risk.
        config: 필터 기준. `None` 이면 기본값.

    Returns:
        (filtered_df, stats). stats 는 각 단계 누적 잔존 수::

            {
                "total": 3500,
                "after_price": 2800,
                "after_volume": 1200,
                "after_market_cap": 1200,
                "after_risk": 1180,
                "after_china": 1150,
                "after_volatility": 800,
                "after_atr_drop": 750,
                "final": 750,
            }
    """
    cfg = {**_default_config(), **(config or {})}

    stats: dict[str, int] = {"total": int(len(df))}

    if df is None or df.empty:
        for key in (
            "after_price", "after_volume", "after_market_cap",
            "after_risk", "after_china", "after_volatility",
            "after_atr_drop", "final",
        ):
            stats[key] = 0
        return df.iloc[0:0].copy() if df is not None else pd.DataFrame(columns=_SCREEN_DF_COLUMNS), stats

    current = df

    # 1) 주가
    mask_price = current["last_price"].fillna(-1.0) >= float(cfg["min_price"])
    current = current[mask_price]
    stats["after_price"] = int(len(current))

    # 2) 거래대금
    mask_vol = current["avg_traded_value_20d"].fillna(-1.0) >= float(cfg["min_traded_value"])
    current = current[mask_vol]
    stats["after_volume"] = int(len(current))

    # 3) 시가총액 (min_market_cap > 0 일 때만 적용)
    min_mc = float(cfg.get("min_market_cap", 0.0))
    if min_mc > 0 and "market_cap" in current.columns:
        # NaN(메타 없음) = 모름 → 통과, 값이 있을 때만 필터 적용
        mask_mc = current["market_cap"].isna() | (current["market_cap"] >= min_mc)
        current = current[mask_mc]
    stats["after_market_cap"] = int(len(current))

    # 4) 관리/위험종목
    if cfg.get("exclude_risk", True):
        # is_risk True 인 종목 제외, NaN/None 은 포함(보수적으로 통과)
        risk_flag = current["is_risk"].fillna(False).astype(bool)
        current = current[~risk_flag]
    stats["after_risk"] = int(len(current))

    # 4.5) 투자경고/투자주의/투자주의환기/단기과열 등 배지 종목 제외 (옵션)
    #   is_risk 와 별개로 caution_flags 가 비어있지 않으면 제외. 섹터 점수가
    #   초저시총 급등주(흔히 단기과열·투자경고 지정)로 왜곡되는 것을 막는다.
    if cfg.get("exclude_caution", False) and "caution_flags" in current.columns:
        caution = current["caution_flags"].fillna("").astype(str).str.strip()
        current = current[caution == ""]
    stats["after_caution"] = int(len(current))

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

    # 7) 최근 1~2일 급락 — D-0/D-1 종가 하락폭 / 직전 ATR9 >= 임계값이면 제외
    #    NaN(데이터 부족) 은 통과. 0 / None 이면 단계 자체를 건너뜀.
    max_drop = float(cfg.get("max_atr_drop_multiple") or 0.0)
    if max_drop > 0 and "recent_atr_drop_mult" in current.columns:
        drop_values = current["recent_atr_drop_mult"]
        mask_drop = ~(drop_values.fillna(-1.0) >= max_drop)
        current = current[mask_drop]
    stats["after_atr_drop"] = int(len(current))

    stats["final"] = int(len(current))
    return current, stats


# ---------------------------------------------------------------------------
# RS 계산 — Phase 1.5 에서 구현
# ---------------------------------------------------------------------------

def calc_weighted_rs(close: pd.Series) -> float:
    """Minervini 가중 RS (public). `_calc_weighted_rs` 와 동일."""
    return _calc_weighted_rs(close)


def _calc_weighted_rs(close: pd.Series) -> float:
    """Minervini 가중 RS.

    RS = (C/C63)×0.4 + (C/C126)×0.2 + (C/C189)×0.2 + (C/C252)×0.2

    지수 대비 비율이 아닌 **절대 가격 비율** 합산 — 지수 수익률이 필요 없으므로
    단독으로 종목 중장기 모멘텀을 나타낸다.
    252영업일(+1) 미만 종목은 NaN 처리.
    """
    s = close.dropna()
    if len(s) < _WEIGHTED_MIN_ROWS:
        return float("nan")
    last = float(s.iloc[-1])
    if last == 0 or pd.isna(last):
        return float("nan")
    total = 0.0
    for period, weight in _WEIGHTED_PERIODS:
        idx = -(period + 1)
        try:
            base = float(s.iloc[idx])
        except IndexError:
            return float("nan")
        if base == 0 or pd.isna(base):
            return float("nan")
        total += (last / base) * weight
    return total


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
    """지수 N일 수익률."""
    if index_prices is None or index_prices.empty or "Close" not in index_prices.columns:
        return float("nan")
    return _period_return(index_prices["Close"], period)


def _relative_strength(stock_return: float, index_return: float) -> float:
    """지수 대비 초과수익률. 지수와 같은 수익률이면 0."""
    if pd.isna(stock_return) or pd.isna(index_return):
        return float("nan")
    return float(stock_return) - float(index_return)


def screen_calc_rs(
    prices: pd.DataFrame,
    index_prices: pd.DataFrame,
    period: int = 20,
) -> pd.Series:
    """상대강도(RS)를 계산한다.

    RS = 종목 N일 수익률 - 지수 N일 수익률

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
    """
    idx_return = _index_return(index_prices, period)

    if prices is None or prices.empty:
        return pd.Series([], dtype=float)

    is_single = "Close" in prices.columns
    if is_single:
        stock_return = _period_return(prices["Close"], period)
        rs = _relative_strength(stock_return, idx_return)
        return pd.Series([rs], dtype=float)

    # wide: columns=티커, 값=close
    rs_map: dict[str, float] = {}
    for col in prices.columns:
        stock_return = _period_return(prices[col], period)
        rs_map[str(col)] = _relative_strength(stock_return, idx_return)
    return pd.Series(rs_map, dtype=float)


# ---------------------------------------------------------------------------
# RS 시간 정합성 — 종목 마지막일이 지수보다 뒤처진 경우 제외
# ---------------------------------------------------------------------------

def screen_filter_by_index_lag(
    tickers: Iterable[str],
    index_code: str,
    max_lag_days: int = 0,
) -> tuple[list[str], int]:
    """종목 캐시 마지막일이 지수 마지막일과 `max_lag_days` 초과로 떨어진 티커 제외.

    RS = 종목 N일 수익률 - 지수 N일 수익률 은 두 시계열이 같은 시점을
    바라볼 때만 의미가 있다. 종목 데이터가 지수보다 뒤처져 있으면 분자/분모의
    기준일이 어긋나 RS 가 시간 정합성을 잃는다. 이 함수는 그런 종목을 사전 제거.

    Args:
        tickers: 검사 대상 티커 리스트.
        index_code: 기준 지수 코드.
        max_lag_days: 허용 캘린더 일수 차이. 기본 0 (완전 일치).

    Returns:
        (passing, excluded). passing 은 통과한 티커 리스트, excluded 는 제외 카운트.

        지수 캐시 자체가 비어 있으면 lag 체크 불가 → 모두 통과 (excluded=0).
    """
    index_last = cache_get_last_index_date(index_code)
    tickers_list = [str(t).strip() for t in tickers if t]
    if index_last is None:
        return tickers_list, 0

    last_dates = cache_get_all_last_price_dates()
    try:
        index_dt = pd.Timestamp(index_last)
    except (ValueError, TypeError):
        return tickers_list, 0

    passing: list[str] = []
    excluded = 0
    for t in tickers_list:
        # cache 는 ticker 를 .upper() 로 저장하지만 한국 6자리 코드는 .upper() 무관.
        last = last_dates.get(t) or last_dates.get(t.upper())
        if last is None:
            excluded += 1
            continue
        try:
            diff = (index_dt - pd.Timestamp(last)).days
        except (ValueError, TypeError):
            excluded += 1
            continue
        if diff > max_lag_days:
            excluded += 1
            continue
        passing.append(t)
    return passing, excluded


# ---------------------------------------------------------------------------
# RS 랭킹 — 캐시에서 바로 Top N 추출
# ---------------------------------------------------------------------------

_RANK_DF_COLUMNS = [
    "rank",
    "ticker",
    "rs",
    "rs_weighted",
    "return_n",
    "index_return_n",
    "last_price",
    "below_ma5",
]

_SECTOR_SUMMARY_COLUMNS = [
    "rank",
    "sector",
    "stock_count",
    "positive_count",
    "positive_ratio",
    "avg_return_n",
    "median_return_n",
    "top_return_n",
    "sector_score",
    "avg_rs",
    "median_rs",
    "avg_rs_weighted",
    "top_ticker",
    "top_name",
    "top_rs_weighted",
]

_SECTOR_MEMBER_COLUMNS = [
    "sector",
    "sector_rank",
    "rank_in_sector",
    "ticker",
    "name_en",
    "name_kr",
    "return_n",
    "rs",
    "rs_weighted",
    "last_price",
    "market_cap",
    "avg_traded_value_20d",
]


def screen_rank_rs(
    tickers: Iterable[str],
    index_code: str,
    period: int = 20,
    top_n: int | None = 20,
) -> pd.DataFrame:
    """캐시에서 티커 시세/지수를 꺼내 RS Top N 랭킹 DataFrame 을 반환한다.

    Args:
        tickers: 대상 티커 (보통 필터 통과 종목).
        index_code: 기준 지수 코드 (예: `^IXIC`, `^GSPC`).
        period: RS 계산 기간. 기본 20.
        top_n: 상위 N개. `None`이면 계산 가능한 전체 랭킹을 반환.

    Returns:
        columns=_RANK_DF_COLUMNS 의 DataFrame. 종목 N일 수익률 내림차순, rank 1부터.
        동일 지수의 초과수익률을 빼므로 이 순서는 RS 내림차순과 동일하다.
        데이터 부족 종목은 NaN 제거.
    """
    # 여유 +10 영업일 (주말/공휴일 흡수). 가중 RS 는 252+1일이 필요하므로 그 이상 확보.
    days = max(period + 10, _WEIGHTED_MIN_ROWS + 10)

    index_df = cache_load_index(index_code, days=days)
    idx_return = _index_return(index_df, period)

    norm_tickers = [str(t).strip().upper() for t in tickers if t and str(t).strip()]
    cached_returns = cache_load_stock_returns(norm_tickers, period)
    cached_metrics = cache_load_computed_metrics(norm_tickers)
    if (
        not cached_returns.empty
        and set(norm_tickers).issubset(cached_metrics.index)
        and pd.notna(idx_return)
    ):
        joined = cached_metrics.join(cached_returns.rename("return_n"), how="inner")
        if not joined.empty:
            joined["rs"] = joined["return_n"].map(
                lambda stock_return: _relative_strength(stock_return, idx_return)
            )
            joined["index_return_n"] = float(idx_return)
            joined = joined.rename(columns={"rs_weighted": "rs_weighted"})
            joined = joined.dropna(subset=["rs"])
            joined = joined.sort_values("return_n", ascending=False, kind="mergesort")
            if top_n is not None:
                joined = joined.head(int(top_n))
            joined = joined.reset_index().rename(columns={"index": "ticker"})
            joined.insert(0, "rank", range(1, len(joined) + 1))
            return joined[_RANK_DF_COLUMNS]

    rows: list[dict] = []
    seen: set[str] = set()

    prices_map = cache_load_prices_bulk(norm_tickers, days=days)

    for t in norm_tickers:
        if t in seen:
            continue
        seen.add(t)

        prices = prices_map.get(t)
        if prices is None or prices.empty:
            continue

        stock_return = _period_return(prices["Close"], period)
        if pd.isna(idx_return) or pd.isna(stock_return):
            continue
        rs = _relative_strength(stock_return, idx_return)
        if pd.isna(rs):
            continue

        last_price = _last_close(prices)
        # 5일선 이탈 여부: 마지막 종가 < 5일 SMA. 데이터 부족이면 False.
        close_series = prices["Close"].dropna()
        if len(close_series) >= 5:
            ma5_last = float(close_series.rolling(5).mean().iloc[-1])
            below_ma5 = bool(last_price < ma5_last) if pd.notna(ma5_last) else False
        else:
            below_ma5 = False

        rs_weighted = _calc_weighted_rs(prices["Close"])

        rows.append(
            {
                "ticker": t,
                "rs": float(rs),
                "rs_weighted": rs_weighted,
                "return_n": float(stock_return),
                "index_return_n": float(idx_return),
                "last_price": last_price,
                "below_ma5": below_ma5,
            }
        )

    if not rows:
        return pd.DataFrame(columns=_RANK_DF_COLUMNS)

    df = pd.DataFrame(rows)
    df = df.sort_values("return_n", ascending=False, kind="mergesort").reset_index(drop=True)
    if top_n is not None:
        df = df.head(int(top_n)).copy()
    else:
        df = df.copy()
    df.insert(0, "rank", range(1, len(df) + 1))
    return df[_RANK_DF_COLUMNS]


def _clean_sector(value: object, unknown_sector: str) -> str:
    if value is None or pd.isna(value):
        return unknown_sector
    text = str(value).strip()
    return text if text else unknown_sector


def _first_display_name(row: pd.Series) -> str:
    for col in ("name_kr", "name_en", "ticker"):
        value = row.get(col)
        if value is not None and not pd.isna(value) and str(value).strip():
            return str(value).strip()
    return ""


def screen_build_sector_rankings(
    ranked: pd.DataFrame,
    metadata: pd.DataFrame | None = None,
    *,
    top_n_per_sector: int = 5,
    min_sector_size: int = 1,
    unknown_sector: str = "미분류",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """섹터별 강도 요약과 섹터 내부 주도주 랭킹을 만든다.

    Args:
        ranked: `screen_rank_rs(..., top_n=None)` 결과처럼 `ticker`, `return_n`, `rs`
            컬럼을 가진 DataFrame. 섹터 분석은 전체 필터 통과 종목 랭킹을 넣는 것이 좋다.
        metadata: `screen_build_screening_df()` 결과 또는 ticker index 를 가진 메타 DataFrame.
            `sector`, `name_en`, `name_kr`, `market_cap`, `avg_traded_value_20d` 등을 병합한다.
        top_n_per_sector: 섹터 점수 계산에 사용할 섹터 내부 상위 종목 수.
            `sector_score = 섹터 내부 상위 N개 return_n 평균`.
        min_sector_size: 이 수보다 종목 수가 적은 섹터는 요약에서 제외.
        unknown_sector: 섹터 메타가 없을 때 사용할 그룹명.

    Returns:
        `(sector_summary, sector_members)`.
        - `sector_summary`: 섹터별 강도 요약, `sector_score` 내림차순.
        - `sector_members`: 섹터별 종목 랭킹, `rank_in_sector` 포함.
    """
    if ranked is None or ranked.empty:
        return (
            pd.DataFrame(columns=_SECTOR_SUMMARY_COLUMNS),
            pd.DataFrame(columns=_SECTOR_MEMBER_COLUMNS),
        )
    if not {"ticker", "return_n", "rs"}.issubset(ranked.columns):
        missing = {"ticker", "return_n", "rs"} - set(ranked.columns)
        raise ValueError(f"ranked에 필요한 컬럼이 없습니다: {sorted(missing)}")

    members = ranked.copy()
    members["ticker"] = members["ticker"].astype(str).str.strip().str.upper()

    if metadata is not None and not metadata.empty:
        meta = metadata.copy()
        if "ticker" in meta.columns:
            meta = meta.set_index("ticker")
        meta.index = meta.index.astype(str).str.strip().str.upper()
        wanted_cols = [
            c
            for c in [
                "sector",
                "name_en",
                "name_kr",
                "market_cap",
                "avg_traded_value_20d",
            ]
            if c in meta.columns
        ]
        if wanted_cols:
            members = members.merge(
                meta[wanted_cols],
                left_on="ticker",
                right_index=True,
                how="left",
                suffixes=("", "_meta"),
            )
            for col in wanted_cols:
                meta_col = f"{col}_meta"
                if meta_col in members.columns:
                    if col in members.columns:
                        members[col] = members[col].combine_first(members[meta_col])
                    else:
                        members[col] = members[meta_col]
                    members = members.drop(columns=[meta_col])

    if "sector" not in members.columns:
        members["sector"] = unknown_sector
    members["sector"] = members["sector"].map(lambda v: _clean_sector(v, unknown_sector))
    members["return_n"] = pd.to_numeric(members["return_n"], errors="coerce")
    members["rs"] = pd.to_numeric(members["rs"], errors="coerce")
    if "rs_weighted" in members.columns:
        members["rs_weighted"] = pd.to_numeric(members["rs_weighted"], errors="coerce")
    else:
        members["rs_weighted"] = np.nan

    members = members.dropna(subset=["return_n", "rs"])
    if members.empty:
        return (
            pd.DataFrame(columns=_SECTOR_SUMMARY_COLUMNS),
            pd.DataFrame(columns=_SECTOR_MEMBER_COLUMNS),
        )

    members = members.sort_values(
        ["sector", "return_n"], ascending=[True, False], kind="mergesort"
    ).copy()
    members["rank_in_sector"] = members.groupby("sector").cumcount() + 1

    summary_rows: list[dict] = []
    for sector, group in members.groupby("sector", sort=False):
        if len(group) < int(min_sector_size):
            continue
        ordered = group.sort_values("return_n", ascending=False, kind="mergesort")
        leaders = ordered.head(max(int(top_n_per_sector), 1))
        top = ordered.iloc[0]
        summary_rows.append(
            {
                "sector": sector,
                "stock_count": int(len(group)),
                "positive_count": int((group["return_n"] > 0).sum()),
                "positive_ratio": float((group["return_n"] > 0).mean()),
                "avg_return_n": float(group["return_n"].mean()),
                "median_return_n": float(group["return_n"].median()),
                "top_return_n": float(top["return_n"]),
                "sector_score": float(leaders["return_n"].mean()),
                "avg_rs": float(group["rs"].mean()),
                "median_rs": float(group["rs"].median()),
                "avg_rs_weighted": (
                    float(group["rs_weighted"].mean())
                    if group["rs_weighted"].notna().any()
                    else float("nan")
                ),
                "top_ticker": top["ticker"],
                "top_name": _first_display_name(top),
                "top_rs_weighted": (
                    float(top["rs_weighted"]) if pd.notna(top["rs_weighted"]) else float("nan")
                ),
            }
        )

    if not summary_rows:
        return (
            pd.DataFrame(columns=_SECTOR_SUMMARY_COLUMNS),
            pd.DataFrame(columns=_SECTOR_MEMBER_COLUMNS),
        )

    summary = pd.DataFrame(summary_rows)
    summary = summary.sort_values(
        ["sector_score", "positive_ratio", "stock_count"],
        ascending=[False, False, False],
        kind="mergesort",
    ).reset_index(drop=True)
    summary.insert(0, "rank", range(1, len(summary) + 1))

    sector_rank_map = dict(zip(summary["sector"], summary["rank"], strict=False))
    members = members[members["sector"].isin(sector_rank_map)].copy()
    members["sector_rank"] = members["sector"].map(sector_rank_map).astype(int)
    members = members.sort_values(
        ["sector_rank", "rank_in_sector"], ascending=[True, True], kind="mergesort"
    ).reset_index(drop=True)

    for col in _SECTOR_MEMBER_COLUMNS:
        if col not in members.columns:
            members[col] = np.nan
    return summary[_SECTOR_SUMMARY_COLUMNS], members[_SECTOR_MEMBER_COLUMNS]


# ---------------------------------------------------------------------------
# 111봉 스윙 하락 구간 감지 (ZigZag — B안)
# ---------------------------------------------------------------------------

def screen_calc_swings(
    df: pd.DataFrame,
    window: int = 111,
    swing_n: int = 5,
) -> list[dict]:
    """최근 window 봉 안에서 고점→저점 하락 스윙 구간 목록 반환 (ZigZag 방식).

    B안: 중간에 반등봉이 섞여도 고점을 다시 뚫지 않는 한 같은 하락 구간으로 간주.
    로컬 극값(SH/SL)을 감지 → 교번 H-L 시퀀스로 정리 → H→L 쌍을 하락 스윙으로 추출.

    Returns:
        list of dicts — start_date, end_date, start_price, end_price,
        duration_bars (봉 수), pct_drop (%)
    """
    if df is None or df.empty:
        return []
    if not {"High", "Low"}.issubset(df.columns):
        return []

    data = df.tail(window)
    n = len(data)
    if n < swing_n * 2 + 2:
        return []

    highs = data["High"]
    lows = data["Low"]

    # 좌우 swing_n 봉 중 극값인 지점 탐지 (rolling center=True)
    w = 2 * swing_n + 1
    roll_max = highs.rolling(w, center=True, min_periods=swing_n + 1).max()
    roll_min = lows.rolling(w, center=True, min_periods=swing_n + 1).min()

    sh_mask = highs == roll_max
    sl_mask = lows == roll_min

    # 시간순 pivot 목록
    pivots: list[tuple[str, object, float]] = []
    for ts in data.index:
        if sh_mask.loc[ts]:
            pivots.append(("H", ts, float(highs.loc[ts])))
        if sl_mask.loc[ts]:
            pivots.append(("L", ts, float(lows.loc[ts])))

    if not pivots:
        return []

    pivots.sort(key=lambda x: x[1])

    # 연속 같은 타입 → 더 극단값으로 병합
    merged: list[list] = []
    for ptype, ts, price in pivots:
        if merged and merged[-1][0] == ptype:
            prev = merged[-1]
            if (ptype == "H" and price > prev[2]) or (ptype == "L" and price < prev[2]):
                prev[1] = ts
                prev[2] = price
        else:
            merged.append([ptype, ts, price])

    # H→L 쌍 → 하락 스윙
    swings: list[dict] = []
    idx_arr = list(data.index)
    for i in range(len(merged) - 1):
        if merged[i][0] != "H" or merged[i + 1][0] != "L":
            continue
        sh_ts, sh_price = merged[i][1], merged[i][2]
        sl_ts, sl_price = merged[i + 1][1], merged[i + 1][2]
        try:
            sh_pos = idx_arr.index(sh_ts)
            sl_pos = idx_arr.index(sl_ts)
        except ValueError:
            continue
        duration = sl_pos - sh_pos
        if duration <= 0:
            continue
        pct_drop = (sl_price - sh_price) / sh_price * 100.0

        def _fmt(ts: object) -> str:
            return ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)

        swings.append({
            "start_date": _fmt(sh_ts),
            "end_date": _fmt(sl_ts),
            "start_price": sh_price,
            "end_price": sl_price,
            "duration_bars": duration,
            "pct_drop": pct_drop,
        })

    return swings


# ---------------------------------------------------------------------------
# 사용 예시 (Phase 1.6 UI 에서 조합):
#   df = screen_build_screening_df(tickers)
#   filtered, stats = screen_apply_filters(df, config)
#   ranked = screen_rank_rs(filtered.index.tolist(), '^IXIC', period=20, top_n=20)
# ---------------------------------------------------------------------------
