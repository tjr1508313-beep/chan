"""한국주식 데이터 API 클라이언트 (agent5-kr-data).

데이터 소스: **FinanceDataReader 단일** (확정 — 2026-04-28).
    - 종목 리스트  →  `fdr.StockListing('KOSPI'/'KOSDAQ')`
    - 일봉 시세    →  `fdr.DataReader('005930', start)`
    - 지수 시세    →  `fdr.DataReader('KS11'/'KQ11', start)`

통합 대비 규칙:
    - 공개 함수명은 `kr_` 접두사
    - 순수 함수 (streamlit import 금지)
    - 미국 쪽 `data.py` 와 시그니처 통일: 같은 OHLCV 컬럼명, 같은 메타 키

미국 쪽과의 차이:
    - 티커: 6자리 숫자 문자열 (예: "005930")
    - 한글명은 `StockListing.Name` 에 그대로 — 별도 매핑 CSV 불필요
    - 거래대금 단위는 **원화** (`Close × Volume`)
    - `is_china` 는 항상 False
    - `is_risk` 는 MVP 보류 (False 고정) — 관리종목 별도 모듈은 추후
"""

from __future__ import annotations

import re
import threading
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Optional

import pandas as pd


# ---------------------------------------------------------------------------
# 내부 유틸
# ---------------------------------------------------------------------------

# 영업일 대비 달력일 버퍼 (미국 쪽과 동일 정책).
_CAL_DAYS_MULTIPLIER = 1.6
_CAL_DAYS_FLOOR = 7
_KR_SECTOR_CSV = Path(__file__).resolve().parent.parent / "data" / "kr_sector_map.csv"


def _calendar_span(days: int) -> int:
    """영업일 `days` 를 안전하게 덮을 달력일 수."""
    return max(_CAL_DAYS_FLOOR, int(days * _CAL_DAYS_MULTIPLIER))


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """FDR `DataReader` 결과를 표준 OHLCV 로 정규화.

    FDR 종목 일봉 컬럼: ['Open','High','Low','Close','Volume','Change'].
    `Change` 는 버리고 OHLCV 만 남김.
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    wanted = ["Open", "High", "Low", "Close", "Volume"]
    existing = [c for c in wanted if c in df.columns]
    out = df[existing].copy()
    out.index = pd.to_datetime(out.index)
    if getattr(out.index, "tz", None) is not None:
        out.index = out.index.tz_localize(None)
    return out.sort_index()


@lru_cache(maxsize=1)
def _load_kr_sector_map() -> dict[str, str]:
    """수동/반자동 한국 업종 매핑 CSV 로드.

    FDR StockListing('KRX')는 현재 업종 컬럼을 제공하지 않는다. 따라서
    `data/kr_sector_map.csv`를 우선 메타 소스로 사용하고, 비어 있으면 None으로 둔다.
    """
    if not _KR_SECTOR_CSV.exists():
        return {}
    try:
        df = pd.read_csv(_KR_SECTOR_CSV, dtype=str).fillna("")
    except Exception:
        return {}
    if "ticker" not in df.columns or "sector" not in df.columns:
        return {}

    out: dict[str, str] = {}
    for _, row in df.iterrows():
        ticker = str(row.get("ticker", "")).strip().zfill(6)
        sector = str(row.get("sector", "")).strip()
        if ticker and sector:
            out[ticker] = sector
    return out


def kr_get_sector(ticker: str) -> str | None:
    """한국 종목 6자리 코드의 업종/섹터 매핑 조회."""
    code = str(ticker).strip().zfill(6)
    return _load_kr_sector_map().get(code)


# ---------------------------------------------------------------------------
# StockListing 캐시 (프로세스 내 1회 — TTL 없음, 새로고침은 프로세스 재시작)
# ---------------------------------------------------------------------------

_LISTING_CACHE: dict[str, pd.DataFrame] = {}
_LISTING_LOCK = threading.Lock()


def _get_listing(market: str) -> pd.DataFrame:
    """`market` ∈ {'KOSPI', 'KOSDAQ'} 의 StockListing 결과 (Code, Name 등).

    ThreadPool 새로고침에서 같은 market 으로 동시 호출될 수 있어
    `_LISTING_LOCK` 으로 보호한다. double-checked locking 으로 hit 경로의
    잠금 비용은 최소화.
    """
    cached = _LISTING_CACHE.get(market)
    if cached is not None:
        return cached

    import FinanceDataReader as fdr

    with _LISTING_LOCK:
        cached = _LISTING_CACHE.get(market)
        if cached is not None:
            return cached
        df = fdr.StockListing(market)
        if "Code" in df.columns:
            df = df.assign(Code=df["Code"].astype(str).str.zfill(6).str.strip())
        _LISTING_CACHE[market] = df
        return df


# ---------------------------------------------------------------------------
# 종목 리스트 — 모집단 정적 필터
# ---------------------------------------------------------------------------
# 사용자 결정 (2026-04-28): 우선주/리츠/ETF/스팩/외국기업은 RS 스크리닝 의미가 다르거나
# 노이즈로 작용하므로 모집단 단계에서 정적 제거. 시가총액/거래대금은 사이드바
# 슬라이더로 동적 조정 가능 (core.py 필터).

# ETF 발행사 키워드 — 한국 ETF 의 종목명 prefix (대소문자 모두 매칭)
_ETF_KEYWORDS = (
    "KODEX", "TIGER", "PLUS", "RISE", "ACE", "SOL", "HANARO",
    "KBSTAR", "ARIRANG", "KOSEF", "KOACT", "WOORI", "마이다스",
    "TIMEFOLIO", "BNK", "FOCUS", "PARAMETRIC",
)


# 우선주 패턴: 이름 끝 '우' / '우A~C' / '2우B' 등
_PREFERRED_NAME_REGEX = r"\d?우[A-Z]?$"
# ETF 키워드 OR 정규식 (대소문자 무관 매칭은 .upper() 비교로 처리)
_ETF_KEYWORDS_REGEX = "|".join(re.escape(kw) for kw in _ETF_KEYWORDS)


def _apply_universe_filter(df: pd.DataFrame) -> pd.DataFrame:
    """모집단 정적 필터 — 우선주/리츠/ETF/스팩/외국기업 제거.

    시가총액·거래대금·관리종목 등 동적 필터는 `screening.core` 에서 처리.
    벡터화된 boolean mask 1회 평가 (apply axis=1 호출 0회).
    """
    if df is None or df.empty or "Code" not in df.columns:
        return df

    code = df["Code"].astype(str)
    name = df["Name"].fillna("").astype(str)
    name_upper = name.str.upper()
    dept = df["Dept"].astype(str) if "Dept" in df.columns else pd.Series("", index=df.index)
    isu = df["ISU_CD"].astype(str) if "ISU_CD" in df.columns else pd.Series("", index=df.index)

    # 우선주: 코드 끝 5 OR 이름 패턴
    excl_pref = code.str.endswith("5") | name.str.contains(_PREFERRED_NAME_REGEX, regex=True, na=False)
    excl_reit = name.str.contains("리츠", na=False)
    excl_spac = name.str.contains("스팩", na=False)
    excl_etf = name_upper.str.contains(_ETF_KEYWORDS_REGEX, regex=True, na=False)
    # 외국기업: Dept 에 '외국' OR ISIN 이 KR 로 시작 안 함
    excl_foreign = dept.str.contains("외국", na=False) | (
        isu.notna() & ~isu.str.startswith("KR") & (isu != "")
    )

    excluded = excl_pref | excl_reit | excl_spac | excl_etf | excl_foreign
    return df[~excluded].copy()


def kr_get_kospi_tickers() -> list[str]:
    """KOSPI 보통주 6자리 티커 리스트 (우선주/리츠/ETF/스팩/외국기업 제외).

    필터 결과는 모집단 단계 정적 제외만 — 시가총액/거래대금은 동적 필터로
    `screening.core.screen_apply_filters` 에서 추가 적용.
    """
    df = _get_listing("KOSPI")
    if "Code" not in df.columns:
        return []
    df = _apply_universe_filter(df)
    return df["Code"].dropna().astype(str).unique().tolist()


def kr_get_kosdaq_tickers() -> list[str]:
    """KOSDAQ 보통주 6자리 티커 리스트 (우선주/리츠/ETF/스팩/외국기업 제외)."""
    df = _get_listing("KOSDAQ")
    if "Code" not in df.columns:
        return []
    df = _apply_universe_filter(df)
    return df["Code"].dropna().astype(str).unique().tolist()


# ---------------------------------------------------------------------------
# 시세
# ---------------------------------------------------------------------------

def kr_load_prices(ticker: str, days: int) -> pd.DataFrame:
    """단일 종목 일봉 OHLCV (최근 `days` 영업일) 반환.

    Args:
        ticker: 6자리 한국 종목코드 (예: "005930").
        days: 조회 기간(영업일 기준).

    Returns:
        index=date, columns=[Open, High, Low, Close, Volume] DataFrame.
    """
    import FinanceDataReader as fdr

    end = datetime.now().date() + timedelta(days=1)
    start = end - timedelta(days=_calendar_span(days))

    raw = fdr.DataReader(ticker, start.isoformat(), end.isoformat())
    df = _normalize_ohlcv(raw)
    if df.empty:
        return df
    return df.tail(days)


def kr_load_index(index_code: str, days: int) -> pd.DataFrame:
    """지수 일봉 반환.

    Args:
        index_code: `KS11` (KOSPI), `KQ11` (KOSDAQ).
        days: 조회 기간(영업일 기준).

    Returns:
        index=date, columns 포함 `Close`.

    Note:
        FDR 의 지수 응답은 종목 일봉과 컬럼이 다르지만 (`UpDown`, `Comp`,
        `Amount`, `MarCap` 등 추가) `Open/High/Low/Close/Volume` 은 동일하게
        포함되어 `_normalize_ohlcv` 로 OHLCV 추출 가능.
    """
    return kr_load_prices(index_code, days)


# ---------------------------------------------------------------------------
# 메타데이터
# ---------------------------------------------------------------------------

def _row_for_ticker(ticker: str) -> Optional[pd.Series]:
    """KOSPI → KOSDAQ 순으로 검색해 매칭되는 1행을 반환. 없으면 None."""
    code = str(ticker).strip().zfill(6)
    for market in ("KOSPI", "KOSDAQ"):
        df = _get_listing(market)
        if "Code" not in df.columns:
            continue
        match = df[df["Code"] == code]
        if not match.empty:
            row = match.iloc[0].copy()
            row["_market"] = market
            return row
    return None


def kr_get_meta(ticker: str) -> dict:
    """종목 메타데이터 반환.

    Returns:
        dict 키 (미국 쪽과 통일):
            - name_en (str): 영문명 — FDR 미제공 시 ticker 그대로
            - name_kr (str | None): 한글명 (FDR `Name`)
            - sector (str | None): `data/kr_sector_map.csv` 매핑값, 없으면 None
            - country (str): 'South Korea'
            - exchange (str | None): 'KOSPI' or 'KOSDAQ'
            - market_cap (float | None): FDR `Marcap` (원화)
            - is_china (bool): 항상 False
            - is_risk (bool): MVP 항상 False (관리종목 필터 보류)
    """
    row = _row_for_ticker(ticker)
    if row is None:
        return {
            "name_en": ticker,
            "name_kr": None,
            "sector": kr_get_sector(ticker),
            "country": "South Korea",
            "exchange": None,
            "market_cap": None,
            "is_china": False,
            "is_risk": False,
        }

    name_kr = row.get("Name")
    if pd.isna(name_kr):
        name_kr = None
    market_cap = row.get("Marcap")
    if pd.isna(market_cap):
        market_cap = None
    else:
        market_cap = float(market_cap)

    return {
        "name_en": str(name_kr) if name_kr else ticker,  # 영문명 미제공 → 한글명 또는 ticker
        "name_kr": str(name_kr) if name_kr else None,
        "sector": kr_get_sector(ticker),
        "country": "South Korea",
        "exchange": str(row.get("_market", "")) or None,
        "market_cap": market_cap,
        "is_china": False,
        "is_risk": False,
    }
