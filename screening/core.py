"""스크리닝 핵심 로직 — RS 계산, 필터링, 랭킹.

통합 대비 규칙:
    - 공개 함수는 `screen_` 접두사
    - `@st.cache_data` 사용 시에도 동일 접두사 유지

핵심 개념:
    ⚠️ RS ≠ RSI(상대강도지수). 여기서 RS는 **지수 대비 종목 수익률 비율**.
    MVP 공식: `RS = (종목 N일 수익률) / (지수 N일 수익률)`
    기본 기간 20일, 사용자 조정 가능 (5~60일).

필터 조건 (모두 AND):
    1. 주가 >= $10
    2. 20일 평균 거래대금 >= $20M
    3. 관리종목/위험종목 제외
    4. 중국기업 제외
    5. 최근 20일 내 일일 변동폭 50% 이상 이력 있는 종목 제외
"""

from __future__ import annotations

import pandas as pd


def screen_calc_rs(
    prices: pd.DataFrame,
    index_prices: pd.DataFrame,
    period: int = 20,
) -> pd.Series:
    """상대강도(RS)를 계산한다.

    RS = (종목 N일 수익률) / (지수 N일 수익률)

    Args:
        prices: 종목 일봉 DataFrame (index: date, columns: OHLCV).
            여러 종목을 한 번에 받는 경우 wide 포맷 (columns: 티커) 가능.
        index_prices: 기준 지수 일봉 DataFrame (close 컬럼 필수).
        period: RS 계산 기간(영업일 기준). 기본 20일.

    Returns:
        티커별 RS 점수를 담은 Series (내림차순 정렬 권장).
    """
    raise NotImplementedError


def screen_apply_filters(
    df: pd.DataFrame,
    config: dict,
) -> tuple[pd.DataFrame, dict]:
    """필터 5종 적용 (주가/거래대금/관리종목/중국기업/변동성).

    Args:
        df: 종목 메타 + 최근 시세가 합쳐진 DataFrame.
        config: 필터 기준 설정. 예시::

            {
                "min_price": 10,            # 달러
                "min_dollar_volume": 20_000_000,
                "max_daily_range_pct": 0.50,
                "lookback_days": 20,
                "exclude_china": True,
                "exclude_risk": True,
            }

    Returns:
        (filtered_df, stats) 튜플. `stats`는 각 단계별 남은 종목 수
        (예: `{"total": 3500, "after_price": 2100, ..., "final": 247}`).
        UI에서 "3,500 → 247" 같은 축소 흐름 표시용.
    """
    raise NotImplementedError
