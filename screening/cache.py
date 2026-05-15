"""SQLite 캐시 계층 — 일일 시세/메타데이터 영속 저장.

매매일지(`trading_journal.db`)와 **분리된 DB 파일** 사용: `screening_cache.db`.
통합 시에도 DB 파일은 분리 유지 권장.

스키마:
    prices (ticker, date, open, high, low, close, volume, dollar_volume)
        PK: (ticker, date)
    metadata (ticker, name_en, name_kr, sector, country, exchange,
              market_cap, is_china, is_risk, updated_at)
        PK: ticker
    index_prices (index_code, date, close)
        PK: (index_code, date)

이 모듈은 **순수 SQLite 영속 저장소**이다.
    - `streamlit` import 금지 (`@st.cache_data` 는 상위 UI 레이어에서 부착)
    - 외부 API 호출 금지 (배치 오케스트레이션은 `screening/batch.py`)
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import pandas as pd


# ---------------------------------------------------------------------------
# DB 경로
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH: Path = _PROJECT_ROOT / "screening_cache.db"


def _db_path() -> str:
    """SQLite 가 받아갈 문자열 경로. (Windows 경로 안전)"""
    return str(DB_PATH)


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """짧게 쓰고 닫는 커넥션 컨텍스트."""
    conn = sqlite3.connect(_db_path())
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        # 미국/한국 새로고침이 동시에 돌 때 쓰기 락 경합을 견디도록 대기시간 확보
        conn.execute("PRAGMA busy_timeout=30000")
        yield conn
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 스키마
# ---------------------------------------------------------------------------

_DDL_PRICES = """
CREATE TABLE IF NOT EXISTS prices (
    ticker        TEXT NOT NULL,
    date          TEXT NOT NULL,
    open          REAL,
    high          REAL,
    low           REAL,
    close         REAL,
    volume        REAL,
    dollar_volume REAL,
    PRIMARY KEY (ticker, date)
)
"""

_DDL_METADATA = """
CREATE TABLE IF NOT EXISTS metadata (
    ticker     TEXT PRIMARY KEY,
    name_en    TEXT,
    name_kr    TEXT,
    sector     TEXT,
    country    TEXT,
    exchange   TEXT,
    market_cap REAL,
    is_china   INTEGER,
    is_risk    INTEGER,
    updated_at TEXT
)
"""

_DDL_INDEX_PRICES = """
CREATE TABLE IF NOT EXISTS index_prices (
    index_code TEXT NOT NULL,
    date       TEXT NOT NULL,
    close      REAL,
    PRIMARY KEY (index_code, date)
)
"""

_DDL_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_prices_date ON prices(date)",
    "CREATE INDEX IF NOT EXISTS idx_index_prices_date ON index_prices(date)",
]


def init_cache() -> None:
    """SQLite 캐시 DB 초기화 (테이블 없으면 생성)."""
    with _connect() as conn:
        conn.execute(_DDL_PRICES)
        conn.execute(_DDL_METADATA)
        conn.execute(_DDL_INDEX_PRICES)
        for ddl in _DDL_INDEXES:
            conn.execute(ddl)


# ---------------------------------------------------------------------------
# 내부 유틸
# ---------------------------------------------------------------------------

def _normalize_date_index(df: pd.DataFrame) -> pd.DataFrame:
    """index 를 `YYYY-MM-DD` 문자열로 재설정 (SQLite 저장용)."""
    if df is None or df.empty:
        return df
    out = df.copy()
    idx = pd.to_datetime(out.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    out.index = idx.strftime("%Y-%m-%d")
    return out


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# 시세 (prices)
# ---------------------------------------------------------------------------

def cache_save_prices(ticker: str, df: pd.DataFrame) -> None:
    """시세 upsert. `dollar_volume = close * volume` 자동 계산.

    Args:
        ticker: 종목 티커 (대문자로 정규화).
        df: `us_load_prices()` 반환 형태. index=date, columns=[Open, High, Low, Close, Volume].
            빈 DF 이면 noop.
    """
    if df is None or df.empty:
        return

    t = ticker.strip().upper()
    norm = _normalize_date_index(df)

    # 컬럼 방어: 없으면 NaN. to_numeric 으로 안전 변환 (변환 실패 시 NaN).
    def col(name: str) -> pd.Series:
        if name not in norm.columns:
            return pd.Series([float("nan")] * len(norm), index=norm.index, dtype=float)
        return pd.to_numeric(norm[name], errors="coerce")

    close = col("Close")
    volume = col("Volume")
    dollar_volume = close * volume

    rows = [
        (
            t,
            str(date_str),
            None if pd.isna(o) else float(o),
            None if pd.isna(h) else float(h),
            None if pd.isna(l) else float(l),
            None if pd.isna(c) else float(c),
            None if pd.isna(v) else float(v),
            None if pd.isna(dv) else float(dv),
        )
        for date_str, o, h, l, c, v, dv in zip(
            norm.index, col("Open"), col("High"), col("Low"),
            close, volume, dollar_volume,
        )
    ]

    sql = (
        "INSERT OR REPLACE INTO prices "
        "(ticker, date, open, high, low, close, volume, dollar_volume) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
    )
    with _connect() as conn:
        conn.executemany(sql, rows)


def cache_load_prices(ticker: str, days: int | None = None) -> pd.DataFrame:
    """시세 조회.

    Args:
        ticker: 종목 티커.
        days: 최근 N영업일만 반환. None 이면 전체.

    Returns:
        index=DatetimeIndex, columns=[Open, High, Low, Close, Volume, dollar_volume] DataFrame.
        데이터 없으면 빈 DF.
    """
    t = ticker.strip().upper()
    with _connect() as conn:
        df = pd.read_sql_query(
            "SELECT date, open, high, low, close, volume, dollar_volume "
            "FROM prices WHERE ticker = ? ORDER BY date ASC",
            conn,
            params=(t,),
        )

    if df.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume", "dollar_volume"])

    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    df = df.rename(
        columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
    )
    if days is not None and days > 0:
        df = df.tail(days)
    return df


def cache_delete_prices(ticker: str) -> int:
    """해당 티커의 모든 시세 행 삭제. 분할/스핀오프 발생 시 옛 가격이
    미조정 상태로 남아 점프가 생기지 않도록 통째로 갈아엎을 때 사용.

    Returns:
        삭제된 행 수.
    """
    t = ticker.strip().upper()
    with _connect() as conn:
        cur = conn.execute("DELETE FROM prices WHERE ticker = ?", (t,))
        return int(cur.rowcount or 0)


def cache_get_last_price_date(ticker: str) -> str | None:
    """해당 티커의 마지막 저장된 날짜(`YYYY-MM-DD`). 없으면 None."""
    t = ticker.strip().upper()
    with _connect() as conn:
        row = conn.execute(
            "SELECT MAX(date) FROM prices WHERE ticker = ?", (t,)
        ).fetchone()
    if row is None or row[0] is None:
        return None
    return str(row[0])


def cache_get_all_last_price_dates() -> dict[str, str]:
    """모든 티커 → 마지막 저장일(`YYYY-MM-DD`) 딕셔너리.

    배치 새로고침에서 'stale 우선' 정렬용. 한 번의 SQL로 모든 티커 일괄 조회.
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT ticker, MAX(date) FROM prices GROUP BY ticker"
        ).fetchall()
    return {str(t): str(d) for t, d in rows if d is not None}


# ---------------------------------------------------------------------------
# 메타데이터
# ---------------------------------------------------------------------------

_META_FIELDS = (
    "name_en",
    "name_kr",
    "sector",
    "country",
    "exchange",
    "market_cap",
    "is_china",
    "is_risk",
)


def cache_save_meta(ticker: str, meta: dict) -> None:
    """메타데이터 upsert. `updated_at` 현재 UTC 시각 기록."""
    if not meta:
        return
    t = ticker.strip().upper()
    updated_at = _utc_now_iso()

    def _bool_to_int(v) -> int | None:
        if v is None:
            return None
        return 1 if v else 0

    row = (
        t,
        meta.get("name_en"),
        meta.get("name_kr"),
        meta.get("sector"),
        meta.get("country"),
        meta.get("exchange"),
        float(meta["market_cap"]) if meta.get("market_cap") not in (None, "") else None,
        _bool_to_int(meta.get("is_china")),
        _bool_to_int(meta.get("is_risk")),
        updated_at,
    )

    sql = (
        "INSERT OR REPLACE INTO metadata "
        "(ticker, name_en, name_kr, sector, country, exchange, "
        "market_cap, is_china, is_risk, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    with _connect() as conn:
        conn.execute(sql, row)


def cache_load_meta(ticker: str) -> dict | None:
    """메타 조회. 없으면 None."""
    t = ticker.strip().upper()
    with _connect() as conn:
        row = conn.execute(
            "SELECT name_en, name_kr, sector, country, exchange, "
            "market_cap, is_china, is_risk, updated_at "
            "FROM metadata WHERE ticker = ?",
            (t,),
        ).fetchone()
    if row is None:
        return None
    return {
        "name_en": row[0],
        "name_kr": row[1],
        "sector": row[2],
        "country": row[3],
        "exchange": row[4],
        "market_cap": row[5],
        "is_china": bool(row[6]) if row[6] is not None else None,
        "is_risk": bool(row[7]) if row[7] is not None else None,
        "updated_at": row[8],
    }


def cache_meta_age_days(ticker: str) -> int | None:
    """메타의 `updated_at` 기준 경과 일수. 없으면 None."""
    m = cache_load_meta(ticker)
    if not m or not m.get("updated_at"):
        return None
    try:
        ts = datetime.strptime(m["updated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None
    delta = datetime.now(timezone.utc) - ts
    return max(0, delta.days)


# ---------------------------------------------------------------------------
# 지수
# ---------------------------------------------------------------------------

def cache_save_index(index_code: str, df: pd.DataFrame) -> None:
    """지수 일봉 upsert (Close 만 저장)."""
    if df is None or df.empty:
        return
    code = index_code.strip()
    norm = _normalize_date_index(df)
    close = norm["Close"] if "Close" in norm.columns else pd.Series(dtype=float)

    rows = [
        (code, str(d), None if pd.isna(c) else float(c))
        for d, c in zip(norm.index, close)
    ]
    with _connect() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO index_prices (index_code, date, close) VALUES (?, ?, ?)",
            rows,
        )


def cache_load_index(index_code: str, days: int | None = None) -> pd.DataFrame:
    """지수 일봉 조회. 반환 DataFrame 의 컬럼은 `Close` 하나."""
    code = index_code.strip()
    with _connect() as conn:
        df = pd.read_sql_query(
            "SELECT date, close FROM index_prices WHERE index_code = ? ORDER BY date ASC",
            conn,
            params=(code,),
        )

    if df.empty:
        return pd.DataFrame(columns=["Close"])

    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    df = df.rename(columns={"close": "Close"})
    if days is not None and days > 0:
        df = df.tail(days)
    return df


def cache_get_last_index_date(index_code: str) -> str | None:
    """지수 마지막 저장일."""
    code = index_code.strip()
    with _connect() as conn:
        row = conn.execute(
            "SELECT MAX(date) FROM index_prices WHERE index_code = ?", (code,)
        ).fetchone()
    if row is None or row[0] is None:
        return None
    return str(row[0])
