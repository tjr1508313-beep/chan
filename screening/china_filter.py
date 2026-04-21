"""중국기업 식별 필터.

미국 거래소(NYSE/NASDAQ)에 상장되어 있지만 HQ가 중국/홍콩인 ADR 종목을
걸러내기 위한 모듈.

판정 순서:
    1) 정적 CSV 리스트(`data/china_stocks.csv`) 조회
    2) yfinance 메타의 `country` 가 China / Hong Kong 인 경우

CSV 는 수동 유지보수가 필요하지만, yfinance `.info` 호출을 아끼는 1차 필터로 유용.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


_CHINA_CSV = Path(__file__).resolve().parent.parent / "data" / "china_stocks.csv"

_CHINA_COUNTRIES = {"China", "Hong Kong"}

_cached_set: set[str] | None = None


def _load_china_set() -> set[str]:
    """CSV 에서 티커 집합을 읽어 메모리 캐시.

    파일이 없거나 비어 있으면 빈 set 반환.
    """
    global _cached_set
    if _cached_set is not None:
        return _cached_set

    if not _CHINA_CSV.exists():
        _cached_set = set()
        return _cached_set

    try:
        df = pd.read_csv(_CHINA_CSV)
        tickers = df["ticker"].astype(str).str.strip().str.upper()
        _cached_set = set(tickers.tolist())
    except Exception:
        _cached_set = set()
    return _cached_set


def is_china_ticker(ticker: str, meta: dict | None = None) -> bool:
    """주어진 티커가 중국기업인지 판정.

    Args:
        ticker: 티커 문자열 (대소문자 무관).
        meta: `us_get_meta()` 결과 dict. 있으면 country 필드를 2차 기준으로 사용.

    Returns:
        bool
    """
    if not ticker:
        return False
    t = ticker.strip().upper()

    if t in _load_china_set():
        return True

    if meta is not None:
        country = meta.get("country")
        if country in _CHINA_COUNTRIES:
            return True

    return False


def reload_china_list() -> None:
    """CSV 변경 후 메모리 캐시를 비움 (개발/운영 중 핫리로드용)."""
    global _cached_set
    _cached_set = None
