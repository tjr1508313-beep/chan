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

병렬화: 시세/메타 모두 `ThreadPoolExecutor` 로 동시 요청.
    - yfinance 가 FDR 보다 레이트 리밋에 민감해 max_workers 보수적으로 잡음.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from typing import Callable, Iterable

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

def _refresh_one_price(t: str, days: int, force: bool) -> tuple[str, str | None, bool]:
    """단일 종목 시세 갱신 — ThreadPool 워커용.

    Returns:
        (kind, failed_ticker_or_None, force_refetched_flag).
        kind ∈ {"updated", "skipped", "failed"}.
    """
    try:
        last_before: str | None = None
        if not force:
            last_before = cache.cache_get_last_price_date(t)
            if last_before is not None:
                gap = _days_since(last_before)
                if gap <= 0:
                    return ("skipped", None, False)
                fetch_days = min(days, max(5, int(gap * 1.1) + 3))
            else:
                fetch_days = days
        else:
            fetch_days = days

        check_splits = last_before is not None and not force
        df = us_data.us_load_prices(t, fetch_days, with_actions=check_splits)
        if df is None or df.empty:
            return ("failed", t, False)

        if check_splits and _detect_new_split(df, last_before):
            df = us_data.us_load_prices(t, days, with_actions=False)
            if df is None or df.empty:
                return ("failed", t, False)
            cache.cache_delete_prices(t)
            cache.cache_save_prices(t, df)
            return ("updated", None, True)

        cache.cache_save_prices(t, df)
        last_after = cache.cache_get_last_price_date(t)
        if last_before is not None and last_after == last_before:
            return ("skipped", None, False)
        return ("updated", None, False)
    except Exception:
        return ("failed", t, False)


def screen_refresh_prices(
    tickers: Iterable[str],
    days: int = 300,
    force: bool = False,
    max_workers: int = 4,
    progress_cb: Callable[[int, int], None] | None = None,
) -> dict:
    """여러 티커의 시세를 캐시에 증분 업데이트 (병렬).

    Args:
        tickers: 티커 리스트.
        days: 캐시에 처음 저장할 때 받아올 최대 영업일 수.
        force: True 면 캐시 무시하고 `days` 만큼 새로 받음.
        max_workers: ThreadPool 동시 요청 수. yfinance 4 권장 (rate limit).
        progress_cb: `(done, total)` 콜백. 매 종목 완료 시 호출.

    Returns:
        `{"updated": int, "skipped": int, "failed": list[str], "force_refetched": int}`.
        `force_refetched` — 분할 자동 감지로 force 재다운로드된 종목 수.
    """
    cache.init_cache()
    tickers_list = [t.strip().upper() for t in tickers if t and str(t).strip()]
    total = len(tickers_list)

    updated = 0
    skipped = 0
    failed: list[str] = []
    force_refetched = 0

    if total == 0:
        return {"updated": 0, "skipped": 0, "failed": [], "force_refetched": 0}

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(_refresh_one_price, t, days, force) for t in tickers_list]
        done = 0
        for fut in as_completed(futures):
            kind, val, fr_flag = fut.result()
            if kind == "updated":
                updated += 1
                if fr_flag:
                    force_refetched += 1
            elif kind == "skipped":
                skipped += 1
            else:
                failed.append(val)  # type: ignore[arg-type]
            done += 1
            if progress_cb is not None:
                progress_cb(done, total)

    return {
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
        "force_refetched": force_refetched,
    }


# ---------------------------------------------------------------------------
# 메타 배치
# ---------------------------------------------------------------------------

def _refresh_one_meta(t: str, ttl_days: int, force: bool) -> tuple[str, str | None]:
    """단일 종목 메타 갱신 — ThreadPool 워커용."""
    try:
        if not force:
            age = cache.cache_meta_age_days(t)
            if age is not None and age < ttl_days:
                return ("skipped", None)

        meta = us_data.us_get_meta(t)
        if not meta:
            return ("failed", t)
        cache.cache_save_meta(t, meta)
        return ("updated", None)
    except Exception:
        return ("failed", t)


def screen_refresh_meta(
    tickers: Iterable[str],
    ttl_days: int = 7,
    force: bool = False,
    max_workers: int = 4,
    progress_cb: Callable[[int, int], None] | None = None,
) -> dict:
    """메타데이터를 TTL 기반으로 증분 업데이트 (병렬).

    yfinance `.info` 는 호출당 0.3~1초로 느리지만 ThreadPool 로 동시 처리 가능.
    """
    cache.init_cache()
    tickers_list = [t.strip().upper() for t in tickers if t and str(t).strip()]
    total = len(tickers_list)

    updated = 0
    skipped = 0
    failed: list[str] = []

    if total == 0:
        return {"updated": 0, "skipped": 0, "failed": []}

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(_refresh_one_meta, t, ttl_days, force) for t in tickers_list]
        done = 0
        for fut in as_completed(futures):
            kind, val = fut.result()
            if kind == "updated":
                updated += 1
            elif kind == "skipped":
                skipped += 1
            else:
                failed.append(val)  # type: ignore[arg-type]
            done += 1
            if progress_cb is not None:
                progress_cb(done, total)

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
