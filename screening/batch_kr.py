"""한국주식 배치 업데이트 오케스트레이션.

미국 쪽 `batch.py` 와 대칭. `screening/data_kr.py`(FDR 클라이언트) 와
`screening/cache.py`(공통 SQLite) 를 연결.

미국 batch 와의 차이:
    - 데이터 소스 = `screening.data_kr` (FDR 단일)
    - 티커 정규화 = `.zfill(6)` (대문자화 X — 한국 코드는 6자리 숫자)
    - 호출 sleep 기본값을 약간 짧게 (FDR 이 yfinance 보다 안정적)

캐시 테이블은 미국과 **공유**한다. 티커 형식이 자연 분리되므로 충돌 없음.
"""

from __future__ import annotations

import time
from datetime import date, datetime
from typing import Iterable

from . import cache
from . import data_kr as kr_data


# ---------------------------------------------------------------------------
# 내부 유틸
# ---------------------------------------------------------------------------

def _normalize_ticker(t: str) -> str:
    """한국 6자리 종목코드 정규화."""
    return str(t).strip().zfill(6)


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

def screen_refresh_prices_kr(
    tickers: Iterable[str],
    days: int = 300,
    force: bool = False,
    sleep_sec: float = 0.1,
) -> dict:
    """한국 종목 시세를 캐시에 증분 업데이트.

    Args, Returns: 미국 `screen_refresh_prices` 와 동일.
    """
    cache.init_cache()
    updated = 0
    skipped = 0
    failed: list[str] = []

    tickers_list = [_normalize_ticker(t) for t in tickers if t and str(t).strip()]

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

            df = kr_data.kr_load_prices(t, fetch_days)
            if df is None or df.empty:
                failed.append(t)
                continue

            cache.cache_save_prices(t, df)

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

    return {"updated": updated, "skipped": skipped, "failed": failed}


# ---------------------------------------------------------------------------
# 메타 배치
# ---------------------------------------------------------------------------

def screen_refresh_meta_kr(
    tickers: Iterable[str],
    ttl_days: int = 7,
    force: bool = False,
    sleep_sec: float = 0.0,
) -> dict:
    """한국 종목 메타데이터를 TTL 기반으로 증분 업데이트.

    FDR `StockListing` 은 한 번 호출에 전체 종목을 받아오므로 종목별 외부 호출
    비용이 없다 (`data_kr` 내부에서 프로세스 캐시). `sleep_sec` 기본 0.0.
    """
    cache.init_cache()
    updated = 0
    skipped = 0
    failed: list[str] = []

    tickers_list = [_normalize_ticker(t) for t in tickers if t and str(t).strip()]

    for t in tickers_list:
        try:
            if not force:
                age = cache.cache_meta_age_days(t)
                if age is not None and age < ttl_days:
                    skipped += 1
                    continue

            meta = kr_data.kr_get_meta(t)
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

def screen_refresh_index_kr(
    index_code: str,
    days: int = 300,
    force: bool = False,
) -> dict:
    """단일 지수 증분 업데이트.

    Args:
        index_code: `KS11` (KOSPI) / `KQ11` (KOSDAQ).
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

        df = kr_data.kr_load_index(index_code, fetch_days)
        if df is None or df.empty:
            return {"updated": 0, "skipped": 0, "failed": [index_code]}

        cache.cache_save_index(index_code, df)
        last_after = cache.cache_get_last_index_date(index_code)
        if last_before is not None and last_after == last_before:
            return {"updated": 0, "skipped": 1, "failed": []}
        return {"updated": 1, "skipped": 0, "failed": []}
    except Exception:
        return {"updated": 0, "skipped": 0, "failed": [index_code]}
