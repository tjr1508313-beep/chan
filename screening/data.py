"""미국주식 데이터 API 클라이언트.

외부 데이터 소스 연동 담당 (agent4-us-data):
    - 나스닥/S&P 500 구성종목 리스트  →  FinanceDataReader
    - 일봉 시세/지수/메타              →  yfinance

통합 대비 규칙:
    - 공개 함수명은 `us_` 접두사
    - `@st.cache_data` 사용 시에도 동일 접두사 유지 (매매일지 캐시와 충돌 방지)

Phase 1.2 이후 실제 구현 예정. 현 단계는 시그니처 스켈레톤만.
"""

from __future__ import annotations

import pandas as pd


def us_get_nasdaq_tickers() -> list[str]:
    """나스닥 구성종목 티커 리스트 반환.

    Source: `FinanceDataReader.StockListing('NASDAQ')`.
    """
    raise NotImplementedError


def us_get_sp500_tickers() -> list[str]:
    """S&P 500 구성종목 티커 리스트 반환.

    Source: `FinanceDataReader.StockListing('S&P500')`.
    """
    raise NotImplementedError


def us_load_prices(ticker: str, days: int) -> pd.DataFrame:
    """단일 종목 일봉 OHLCV (최근 `days` 영업일) 반환.

    Args:
        ticker: 미국주식 티커 (예: "AAPL").
        days: 조회 기간(영업일 기준).

    Returns:
        index=date, columns=[Open, High, Low, Close, Volume] DataFrame.
        `auto_adjust=True` 적용 권장 (분할/배당 조정).
    """
    raise NotImplementedError


def us_load_index(index_code: str, days: int) -> pd.DataFrame:
    """지수 일봉 반환.

    Args:
        index_code: `^IXIC` (NASDAQ 종합), `^GSPC` (S&P 500).
        days: 조회 기간(영업일 기준).

    Returns:
        index=date, columns 포함 `Close`.
    """
    raise NotImplementedError


def us_get_meta(ticker: str) -> dict:
    """종목 메타데이터 반환.

    Returns:
        dict 키:
            - name_en (str): 영문명
            - name_kr (str | None): 한글명 (매핑 테이블 있을 때만)
            - sector (str | None)
            - country (str | None)
            - exchange (str | None)
            - market_cap (float | None)
            - is_china (bool)
            - is_risk (bool)
    """
    raise NotImplementedError
