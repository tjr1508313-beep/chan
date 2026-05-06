"""배치 업데이트 오케스트레이션.

`screening/data.py`(agent4: 외부 API 클라이언트) 와
`screening/cache.py`(SQLite 영속 저장) 를 연결하는 레이어.

증분 업데이트 전략:
    - 시세: `cache_get_last_price_date()` 이후 영업일만 다운로드
    - 메타: `cache_meta_age_days()` 가 TTL 이상이면 재조회
    - `force=True` 면 캐시 무시하고 전부 다시 받음

분할(Stock Split) 자동 감지:
    - `last_before` 가 있는 종목은 `with_actions=True` 로 받아 Stock Splits 컬럼 검사
    - last_before 이후 새 split 이 발견되면 캐시의 옛 가격이 미조정 상태이므로
      그 종목만 force fetch (전체 days 재다운로드, auto_adjust=True 로 재조정)
    - 추가 API 호출은 없음 (같은 다운로드에 actions 컬럼만 추가)

yfinance 레이트 리밋 대응: 호출 사이 `sleep_sec` 휴식. 기본 0.2s.
"""

from __future__ import annotations

import time
from datetime import date, datetime
from typing import Iterable

import pandas as pd

from . import cache
from . import data as us_data


def _detect_new_split(df: pd.DataFrame, last_before: str) -> bool:
    """`last_before` 이후 발생한 stock split 이 있는지.

    Args:
        df: `us_load_prices(..., with_actions=True)` 결과.
            `Stock Splits` 컬럼 포함 가정.
        last_before: 캐시에 마지막으로 저장된 날짜 (`YYYY-MM-DD`).

    Returns:
        last_before 이후에 split (값 != 0, NaN 아님) 한 건이라도 있으면 True.
    """
    if df is None or df.empty or "Stock Splits" not in df.columns:
        return False
    try:
        cutoff = pd.Timestamp(last_before)
    except (ValueError, TypeError):
        return False
    s = df["Stock Splits"]
    s = s[(s.index > cutoff) & s.notna() & (s != 0)]
    return not s.empty


# ---------------------------------------------------------------------------
# 내부 유틸
# ---------------------------------------------------------------------------

def _days_since(date_str: str) -> int:
    """`YYYY-MM-DD` 문자열에서 오늘까지 달력일 차이."""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return 10_000
    return (date.today() - d).days


# ---------------------------------------------------------------------------
# 시세 배치
# ---------------------------------------------------------------------------

def screen_refresh_prices(
    tickers: Iterable[str],
    days: int = 300,
    force: bool = False,
    sleep_sec: float = 0.2,
) -> dict:
    """여러 티커의 시세를 캐시에 증분 업데이트.

    Args:
        tickers: 티커 리스트.
        days: 캐시에 처음 저장할 때 받아올 최대 영업일 수.
        force: True 면 캐시 무시하고 `days` 만큼 새로 받음.
        sleep_sec: yfinance 호출 사이 sleep (레이트 리밋 대응).

    Returns:
        `{"updated": int, "skipped": int, "failed": list[str], "force_refetched": int}`.

        `force_refetched` — 분할 자동 감지로 force 재다운로드된 종목 수.

    증분 로직:
        - 캐시에 데이터 없음 → `days` 영업일치 다운로드
        - 캐시 있음 + 마지막 저장일 = 오늘 → skip (이미 최신)
        - 캐시 있음 + 오래된 경우 → 마지막 저장일 다음날 ~ 오늘 범위만 다운로드
          (단순화를 위해 `days`를 캡으로 쓰되, gap 이 그 이상이면 `days` 전체 재다운)
        - 캐시 있음 + 다운로드 결과에 신규 split 발견 → 그 종목만 force 재시도
    """
    cache.init_cache()
    updated = 0
    skipped = 0
    failed: list[str] = []
    force_refetched = 0

    tickers_list = [t.strip().upper() for t in tickers if t and str(t).strip()]

    for t in tickers_list:
        try:
            last_before: str | None = None
            if not force:
                last_before = cache.cache_get_last_price_date(t)
                if last_before is not None:
                    gap = _days_since(last_before)
                    if gap <= 0:
                        skipped += 1
                        continue
                    fetch_days = min(days, max(5, int(gap * 1.1) + 3))
                else:
                    fetch_days = days
            else:
                fetch_days = days

            # 캐시에 옛 데이터가 있을 때만 split 감지 의미 있음.
            # 신규 ticker(last_before is None) 는 어차피 전체 다운로드라 검사 불필요.
            check_splits = last_before is not None and not force
            df = us_data.us_load_prices(t, fetch_days, with_actions=check_splits)
            if df is None or df.empty:
                failed.append(t)
                continue

            # 신규 split 발견 → 전체 days 재다운로드 (캐시 옛 가격이 미조정이라 점프 발생).
            # 재다운로드는 auto_adjust=True 라 받은 행은 새 split 기준으로 재조정됨.
            # 다만 days 범위 밖의 옛 캐시 행은 미조정 상태 → 통째로 DELETE 후 INSERT.
            if check_splits and _detect_new_split(df, last_before):
                df = us_data.us_load_prices(t, days, with_actions=False)
                if df is None or df.empty:
                    failed.append(t)
                    continue
                cache.cache_delete_prices(t)
                cache.cache_save_prices(t, df)
                force_refetched += 1
                updated += 1
                continue

            cache.cache_save_prices(t, df)

            # 실제 새 행이 들어왔는지로 updated/skipped 구분
            last_after = cache.cache_get_last_price_date(t)
            if last_before is not None and last_after == last_before:
                skipped += 1
            else:
                updated += 1
        except Exception:
            failed.append(t)
        finally:
            if sleep_sec > 0:
                time.sleep(sleep_sec)

    return {
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
        "force_refetched": force_refetched,
    }


# ---------------------------------------------------------------------------
# 메타 배치
# ---------------------------------------------------------------------------

def screen_refresh_meta(
    tickers: Iterable[str],
    ttl_days: int = 7,
    force: bool = False,
    sleep_sec: float = 0.3,
) -> dict:
    """메타데이터를 TTL 기반으로 증분 업데이트.

    Args:
        tickers: 티커 리스트.
        ttl_days: TTL 만료 기준 (일). 기본 7일.
        force: True 면 TTL 무시하고 전부 재조회.
        sleep_sec: yfinance `.info` 호출은 느리므로 더 넉넉히.

    Returns:
        `{"updated": int, "skipped": int, "failed": list[str]}`.
    """
    cache.init_cache()
    updated = 0
    skipped = 0
    failed: list[str] = []

    tickers_list = [t.strip().upper() for t in tickers if t and str(t).strip()]

    for t in tickers_list:
        try:
            if not force:
                age = cache.cache_meta_age_days(t)
                if age is not None and age < ttl_days:
                    skipped += 1
                    continue

            meta = us_data.us_get_meta(t)
            if not meta:
                failed.append(t)
                continue
            cache.cache_save_meta(t, meta)
            updated += 1
        except Exception:
            failed.append(t)
        finally:
            if sleep_sec > 0:
                time.sleep(sleep_sec)

    return {"updated": updated, "skipped": skipped, "failed": failed}


# ---------------------------------------------------------------------------
# 지수 배치
# ---------------------------------------------------------------------------

def screen_refresh_index(
    index_code: str,
    days: int = 300,
    force: bool = False,
) -> dict:
    """단일 지수 증분 업데이트.

    Args:
        index_code: 예) `^IXIC`, `^GSPC`.
        days: 최초 로드 시 영업일 수.
        force: 캐시 무시하고 전체 재로드.

    Returns:
        `{"updated": int, "skipped": int, "failed": list[str]}`.
    """
    cache.init_cache()
    try:
        last_before: str | None = None
        if not force:
            last_before = cache.cache_get_last_index_date(index_code)
            if last_before is not None:
                gap = _days_since(last_before)
                if gap <= 0:
                    return {"updated": 0, "skipped": 1, "failed": []}
                fetch_days = min(days, max(5, int(gap * 1.1) + 3))
            else:
                fetch_days = days
        else:
            fetch_days = days

        df = us_data.us_load_index(index_code, fetch_days)
        if df is None or df.empty:
            return {"updated": 0, "skipped": 0, "failed": [index_code]}

        cache.cache_save_index(index_code, df)
        last_after = cache.cache_get_last_index_date(index_code)
        if last_before is not None and last_after == last_before:
            return {"updated": 0, "skipped": 1, "failed": []}
        return {"updated": 1, "skipped": 0, "failed": []}
    except Exception:
        return {"updated": 0, "skipped": 0, "failed": [index_code]}
