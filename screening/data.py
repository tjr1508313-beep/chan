"""미국주식 데이터 API 클라이언트.

외부 데이터 소스 연동 담당 (agent4-us-data):
    - 나스닥/S&P 500 구성종목 리스트  →  FinanceDataReader
    - 일봉 시세/지수/메타              →  yfinance

통합 대비 규칙:
    - 공개 함수명은 `us_` 접두사
    - `@st.cache_data` 사용 시에도 동일 접두사 유지 (매매일지 캐시와 충돌 방지)

캐시 데코레이터는 백엔드(`screening/cache.py`)에서 SQLite 캐시와 함께 일괄 부착 예정이므로
이 모듈은 **순수 함수**로만 구성한다 (streamlit import 금지).
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .china_filter import is_china_ticker


# ---------------------------------------------------------------------------
# 내부 유틸
# ---------------------------------------------------------------------------

# 영업일 대비 달력일 버퍼. 주말/공휴일 고려해 넉넉히 곱함.
_CAL_DAYS_MULTIPLIER = 1.6
_CAL_DAYS_FLOOR = 7

# 한글명 매핑 CSV (ticker → 한글명). 없거나 매핑 안 되어 있으면 None.
_KR_NAME_CSV = Path(__file__).resolve().parent.parent / "data" / "us_ticker_kr.csv"
_KR_NAME_CACHE: dict[str, str] | None = None


def _load_kr_name_map() -> dict[str, str]:
    """티커 → 한글명 매핑 로드 (프로세스 내 1회 캐시)."""
    global _KR_NAME_CACHE
    if _KR_NAME_CACHE is not None:
        return _KR_NAME_CACHE

    if not _KR_NAME_CSV.exists():
        _KR_NAME_CACHE = {}
        return _KR_NAME_CACHE

    try:
        df = pd.read_csv(_KR_NAME_CSV, dtype=str).dropna(subset=["ticker", "name_kr"])
        _KR_NAME_CACHE = {
            str(row["ticker"]).strip().upper(): str(row["name_kr"]).strip()
            for _, row in df.iterrows()
            if str(row["ticker"]).strip() and str(row["name_kr"]).strip()
        }
    except Exception:
        _KR_NAME_CACHE = {}
    return _KR_NAME_CACHE


def us_get_kr_name(ticker: str) -> str | None:
    """티커에 매핑된 한글명 반환. 없으면 None."""
    if not ticker:
        return None
    return _load_kr_name_map().get(str(ticker).strip().upper())


def _calendar_span(days: int) -> int:
    """영업일 `days` 를 안전하게 덮을 달력일 수."""
    return max(_CAL_DAYS_FLOOR, int(days * _CAL_DAYS_MULTIPLIER))


def _normalize_ohlcv(df: pd.DataFrame, with_actions: bool = False) -> pd.DataFrame:
    """yfinance 다중 컬럼/빈 DF 등을 표준 OHLCV 로 정규화.

    Args:
        df: yfinance 원본 DataFrame.
        with_actions: True 면 `Stock Splits` / `Dividends` 컬럼도 보존.
            (분할 감지용 — `screen_refresh_prices` 가 사용)
    """
    base_cols = ["Open", "High", "Low", "Close", "Volume"]
    if df is None or df.empty:
        cols = base_cols + (["Stock Splits", "Dividends"] if with_actions else [])
        return pd.DataFrame(columns=cols)

    # yfinance 가 MultiIndex 컬럼을 돌려줄 때 대비
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)

    wanted = base_cols + (["Stock Splits", "Dividends"] if with_actions else [])
    existing = [c for c in wanted if c in df.columns]
    out = df[existing].copy()
    idx = pd.to_datetime(out.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    out.index = idx
    return out.sort_index()


# ---------------------------------------------------------------------------
# 종목 리스트
# ---------------------------------------------------------------------------

def us_get_nasdaq_tickers() -> list[str]:
    """나스닥 구성종목 티커 리스트 반환.

    Source: `FinanceDataReader.StockListing('NASDAQ')`.
    """
    import FinanceDataReader as fdr

    df = fdr.StockListing("NASDAQ")
    # 컬럼명은 버전에 따라 'Symbol' 또는 'Ticker' 일 수 있음
    col = "Symbol" if "Symbol" in df.columns else ("Ticker" if "Ticker" in df.columns else df.columns[0])
    tickers = df[col].dropna().astype(str).str.strip().str.upper().unique().tolist()
    return [t for t in tickers if t]


def us_get_sp500_tickers() -> list[str]:
    """S&P 500 구성종목 티커 리스트 반환.

    Source: `FinanceDataReader.StockListing('S&P500')`.
    """
    import FinanceDataReader as fdr

    df = fdr.StockListing("S&P500")
    col = "Symbol" if "Symbol" in df.columns else ("Ticker" if "Ticker" in df.columns else df.columns[0])
    tickers = df[col].dropna().astype(str).str.strip().str.upper().unique().tolist()
    return [t for t in tickers if t]


# ---------------------------------------------------------------------------
# 시세
# ---------------------------------------------------------------------------

def us_load_prices(
    ticker: str, days: int, with_actions: bool = False
) -> pd.DataFrame:
    """단일 종목 일봉 OHLCV (최근 `days` 영업일) 반환.

    Args:
        ticker: 미국주식 티커 (예: "AAPL").
        days: 조회 기간(영업일 기준).
        with_actions: True 면 `Stock Splits` / `Dividends` 컬럼도 함께 반환.
            (분할 감지용 — 추가 API 호출 없이 같은 다운로드에 포함)

    Returns:
        index=date, columns=[Open, High, Low, Close, Volume,
        (with_actions 시 +Stock Splits, Dividends)] DataFrame.
        `auto_adjust=True` 적용 (분할/배당 조정 — RS 계산 오염 방지).
    """
    import yfinance as yf

    end = date.today() + timedelta(days=1)
    start = end - timedelta(days=_calendar_span(days))

    raw = yf.download(
        ticker,
        start=start.isoformat(),
        end=end.isoformat(),
        auto_adjust=True,
        actions=with_actions,
        progress=False,
        threads=False,
    )
    df = _normalize_ohlcv(raw, with_actions=with_actions)
    if df.empty:
        return df
    return df.tail(days)


def us_load_index(index_code: str, days: int) -> pd.DataFrame:
    """지수 일봉 반환.

    Args:
        index_code: `^IXIC` (NASDAQ 종합), `^GSPC` (S&P 500).
        days: 조회 기간(영업일 기준).

    Returns:
        index=date, columns 포함 `Close`.
    """
    # 지수도 결국 yfinance 티커 다운로드와 동일
    return us_load_prices(index_code, days)


# ---------------------------------------------------------------------------
# 메타데이터 & 관리종목
# ---------------------------------------------------------------------------

def _is_risk_from_info(info: dict) -> bool:
    """MVP 수준의 관리/위험 종목 간단 판정.

    - EQUITY 가 아닌 경우 (ETF/MUTUALFUND/WARRANT 등)
    - market_cap 정보가 아예 없거나 0 (상장 폐지 임박/저품질 티커 가능성)
    - regularMarketPrice 가 없는 경우

    공시 기반 정교화는 추후 작업.
    """
    if not info:
        return True

    qtype = info.get("quoteType")
    if qtype and qtype != "EQUITY":
        return True

    mcap = info.get("marketCap")
    if mcap is None or mcap == 0:
        return True

    price = info.get("regularMarketPrice") or info.get("currentPrice")
    if price is None:
        return True

    return False


def us_get_meta(ticker: str) -> dict:
    """종목 메타데이터 반환.

    Returns:
        dict 키:
            - name_en (str): 영문명
            - name_kr (str | None): 한글명 (매핑 테이블 있을 때만 — MVP 단계에선 None)
            - sector (str | None)
            - country (str | None)
            - exchange (str | None)
            - market_cap (float | None)
            - is_china (bool)
            - is_risk (bool)
    """
    import yfinance as yf

    info: dict = {}
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception:
        info = {}

    name_en = (
        info.get("longName")
        or info.get("shortName")
        or info.get("displayName")
        or ticker
    )
    sector = info.get("sector")
    country = info.get("country")
    exchange = info.get("exchange") or info.get("fullExchangeName")
    market_cap = info.get("marketCap")

    meta: dict = {
        "name_en": name_en,
        "name_kr": us_get_kr_name(ticker),
        "sector": sector,
        "country": country,
        "exchange": exchange,
        "market_cap": market_cap,
        "is_china": False,
        "is_risk": False,
    }
    meta["is_china"] = is_china_ticker(ticker, meta=meta)
    meta["is_risk"] = _is_risk_from_info(info)
    return meta
