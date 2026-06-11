"""한국주식 배치 업데이트 오케스트레이션.

미국 쪽 `batch.py` 와 대칭. `screening/data_kr.py`(FDR 클라이언트) 와
`screening/cache.py`(공통 SQLite) 를 연결.

미국 batch 와의 차이:
    - 데이터 소스 = `screening.data_kr` (FDR 단일)
    - 티커 정규화 = `.zfill(6)` (대문자화 X — 한국 코드는 6자리 숫자)
    - 시세 다운로드는 `ThreadPoolExecutor` 로 병렬화 (FDR HTTP I/O 바운드).

캐시 테이블은 미국과 **공유**한다. 티커 형식이 자연 분리되므로 충돌 없음.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from typing import Callable, Iterable

from . import cache
from . import data_kr as kr_data
from . import kr_risk


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

def _refresh_one_price(t: str, days: int, force: bool) -> tuple[str, str | None]:
    """단일 종목 시세 갱신 — ThreadPool 워커용.

    Returns:
        ("updated"|"skipped"|"failed", failed_ticker_or_None)
    """
    try:
        last_before: str | None = None
        if not force:
            last_before = cache.cache_get_last_price_date(t)
            if last_before is not None:
                gap = _days_since(last_before)
                if gap <= 0:
                    return ("skipped", None)
                fetch_days = min(days, max(5, int(gap * 1.1) + 3))
            else:
                fetch_days = days
        else:
            fetch_days = days

        df = kr_data.kr_load_prices(t, fetch_days)
        if df is None or df.empty:
            return ("failed", t)

        cache.cache_save_prices(t, df)
        last_after = cache.cache_get_last_price_date(t)
        if last_before is not None and last_after == last_before:
            return ("skipped", None)
        return ("updated", None)
    except Exception:
        return ("failed", t)


def screen_refresh_prices_kr(
    tickers: Iterable[str],
    days: int = 300,
    force: bool = False,
    max_workers: int = 8,
    progress_cb: Callable[[int, int], None] | None = None,
) -> dict:
    """한국 종목 시세를 캐시에 증분 업데이트 (병렬).

    Args:
        tickers: 6자리 코드 리스트.
        days: 초회 다운로드 시 영업일 수.
        force: True 면 캐시 무시.
        max_workers: ThreadPool 동시 요청 수. FDR 8 권장.
        progress_cb: `(done, total)` 콜백. 매 종목 완료 시 호출.

    Returns: 미국 `screen_refresh_prices` 와 동일 형태.
    """
    cache.init_cache()
    tickers_list = [_normalize_ticker(t) for t in tickers if t and str(t).strip()]
    total = len(tickers_list)

    updated = 0
    skipped = 0
    failed: list[str] = []

    if total == 0:
        return {"updated": 0, "skipped": 0, "failed": []}

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(_refresh_one_price, t, days, force) for t in tickers_list]
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
# 메타 배치
# ---------------------------------------------------------------------------

def screen_refresh_meta_kr(
    tickers: Iterable[str],
    ttl_days: int = 7,
    force: bool = False,
) -> dict:
    """한국 종목 메타데이터를 TTL 기반으로 증분 업데이트.

    FDR `StockListing` 은 한 번 호출에 전체 종목을 받아오므로 종목별 외부 호출
    비용이 없다 (`data_kr` 내부에서 프로세스 캐시). 병렬화 불필요.
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

    return {"updated": updated, "skipped": skipped, "failed": failed}


def screen_refresh_risk_kr() -> dict:
    """LS OpenAPI 로 관리/거래정지/시장경보 플래그를 갱신 (메타 TTL 무관, 매 실행).

    메타 갱신 *이후* 호출해야 한다 (cache_save_meta 가 caution_flags 를 NULL 로
    덮으므로). LS 키 미설정/실패 시 flags 가 빈 dict → 전체 클리어로 기존 플래그가
    날아가지 않도록 갱신을 건너뛴다.
    """
    cache.init_cache()
    flags = kr_risk.kr_fetch_risk_flags()
    if not flags:
        return {"updated": 0, "skipped": True}
    cache.update_risk_flags(flags)
    return {"updated": len(flags), "skipped": False}


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
        chart_ready = len(cache.cache_load_index_chart_snapshot(index_code, days=110)) >= 110
        last_before: str | None = None
        if not force:
            last_before = cache.cache_get_last_index_date(index_code)
            if last_before is not None:
                gap = _days_since(last_before)
                if gap <= 0 and chart_ready:
                    return {"updated": 0, "skipped": 1, "failed": []}
                fetch_days = (
                    min(days, max(5, int(gap * 1.1) + 3))
                    if chart_ready
                    else max(days, 111)
                )
            else:
                fetch_days = max(days, 111)
        else:
            fetch_days = max(days, 111)

        df = kr_data.kr_load_index(index_code, fetch_days)
        if df is None or df.empty:
            return {"updated": 0, "skipped": 0, "failed": [index_code]}

        cache.cache_save_index(index_code, df)
        chart_rows = cache.cache_save_index_chart_snapshot(index_code, df, days=110)
        last_after = cache.cache_get_last_index_date(index_code)
        if last_before is not None and last_after == last_before and chart_ready:
            return {"updated": 0, "skipped": 1, "failed": []}
        if chart_rows == 0 and not chart_ready:
            return {"updated": 0, "skipped": 0, "failed": [index_code]}
        return {"updated": 1, "skipped": 0, "failed": []}
    except Exception:
        return {"updated": 0, "skipped": 0, "failed": [index_code]}
